"""Extended predictors for the XGBoost models: circulation indices and cyclic MJO.

Ported from the varsha-drishti-model training repo so inference here builds the same
columns the boosters were fitted on. Both sources are date-global (one value per day,
shared by every cell), so they are engineered on the daily series and merged on `date`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
INDICES_W4_PATH = ROOT / "data" / "raw" / "indices_w4" / "monsoon_indices_w4.parquet"
RMM_PATH = ROOT / "data" / "raw" / "indices" / "rmm_mjo.txt"
ECMWF_PATH = ROOT / "data" / "processed" / "ecmwf_s2s_features.parquet"
FEATURES_PATH = ROOT / "data" / "processed" / "features.parquet"
ONSET_LABELS_PATH = ROOT / "data" / "processed" / "onset_labels.parquet"

# Frozen at build time by scripts/export_xgb_tables.py. The nightly Action has the repo,
# not the 825 MB archive or the raw index files, so inference reads these instead.
CLIM_TRAIN_PATH = ROOT / "data" / "processed" / "clim_train_only.parquet"
EXTENDED_DAILY_PATH = ROOT / "data" / "processed" / "extended_daily.parquet"

CLIM_COLS = ["clim_rain_doy", "clim_dryday_doy", "clim_onset_doy",
             "clim_first_cand_doy", "clim_false_rate"]
DRY_DAY_THRESHOLD_MM = 2.5  # matches days_since_rain's threshold

CIRCULATION_INDICES = [
    "llj_u850", "wf_shear", "wy_shear", "v850_bob", "trough_slp",
    "tt_grad", "olr_eio", "olr_bob", "olr_kar", "olr_merid",
]

VALID_TIME_HORIZONS = (7, 14, 21, 28)

# The boosters' anomaly baseline is train-years-only; inference must reuse it unchanged.
TRAIN_YEARS = (1991, 2015)

EXTENDED_FEATURES = (
    [f"{c}_{s}" for c in CIRCULATION_INDICES for s in ("anom_5d", "anom_15d", "tend10")]
    + ["mjo_cos", "mjo_sin", "mjo_inactive", "rmm1_tend10", "rmm2_tend10",
       "mjo_angvel10", "mjo_amp_15d"]
    + [f"mjo_{t}_valid_{h}d" for h in VALID_TIME_HORIZONS for t in ("cos", "sin")]
)

ECMWF_FEATURES = [f"ecmwf_{s}_{h}d" for s in ("mean_mm", "std_mm") for h in VALID_TIME_HORIZONS]


def _doy_climatology(series: pd.Series, train_years: tuple[int, int]) -> pd.Series:
    """Day-of-year climatology from train years only, smoothed over 15 days."""
    lo, hi = train_years
    train = series[(series.index.year >= lo) & (series.index.year <= hi)]
    clim = train.groupby(train.index.dayofyear).mean()
    clim = clim.reindex(range(1, 367)).interpolate(limit_direction="both")
    return clim.rolling(15, center=True, min_periods=1).mean()


def load_circulation_indices() -> pd.DataFrame:
    df = pd.read_parquet(INDICES_W4_PATH)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def build_circulation_features(train_years: tuple[int, int] = TRAIN_YEARS) -> pd.DataFrame:
    """5d/15d anomaly means and a 10-day tendency for each circulation index."""
    raw = load_circulation_indices()
    out = {}
    for col in CIRCULATION_INDICES:
        series = raw[col]
        clim = _doy_climatology(series, train_years)
        anom = series - series.index.dayofyear.map(clim).to_numpy()
        anom_5d = anom.rolling(5, min_periods=1).mean()
        out[f"{col}_anom_5d"] = anom_5d
        out[f"{col}_anom_15d"] = anom.rolling(15, min_periods=1).mean()
        out[f"{col}_tend10"] = anom_5d - anom_5d.shift(10)
    return pd.DataFrame(out, index=raw.index)


def load_rmm_daily() -> pd.DataFrame:
    """Raw RMM table, daily from 1974 so the lags reach past the season edge."""
    df = pd.read_csv(RMM_PATH, skiprows=2, sep=r"\s+", usecols=[0, 1, 2, 3, 4, 5, 6],
                     names=["year", "month", "day", "rmm1", "rmm2", "phase", "amplitude"])
    df = df[df["rmm1"].abs() < 100]  # drop the 1e36 / 999 missing sentinels
    df.index = pd.to_datetime(dict(year=df.year, month=df.month, day=df.day))
    return df[["rmm1", "rmm2", "phase", "amplitude"]].sort_index()


def build_mjo_features() -> pd.DataFrame:
    """Cyclic phase, propagation speed, an inactive flag, and phase at valid time."""
    rmm = load_rmm_daily()
    angle = np.arctan2(rmm["rmm2"], rmm["rmm1"])
    amp = np.sqrt(rmm["rmm1"] ** 2 + rmm["rmm2"] ** 2)

    out = pd.DataFrame(index=rmm.index)
    out["mjo_cos"] = np.cos(angle)
    out["mjo_sin"] = np.sin(angle)
    out["mjo_inactive"] = (amp < 1.0).astype(float)
    out["rmm1_tend10"] = rmm["rmm1"] - rmm["rmm1"].shift(10)
    out["rmm2_tend10"] = rmm["rmm2"] - rmm["rmm2"].shift(10)

    # angular velocity over 10 days, unwrapped to (-pi, pi]
    delta = angle - angle.shift(10)
    angvel10 = (delta + np.pi) % (2 * np.pi) - np.pi
    out["mjo_angvel10"] = angvel10
    out["mjo_amp_15d"] = amp.rolling(15, min_periods=1).mean()

    # where the MJO will BE at valid time, at the last-10-day angular rate
    angvel_per_day = angvel10 / 10.0
    for h in VALID_TIME_HORIZONS:
        angle_valid = angle + angvel_per_day * h
        out[f"mjo_cos_valid_{h}d"] = np.cos(angle_valid)
        out[f"mjo_sin_valid_{h}d"] = np.sin(angle_valid)
    return out


def build_extended_frame(train_years: tuple[int, int] = TRAIN_YEARS) -> pd.DataFrame:
    """Date-indexed frame of every extended predictor, ready to merge on `date`."""
    return build_circulation_features(train_years).join(build_mjo_features(), how="left")


def extended_daily() -> pd.DataFrame:
    """The frozen extended table, falling back to rebuilding it from the raw indices."""
    if EXTENDED_DAILY_PATH.exists():
        df = pd.read_parquet(EXTENDED_DAILY_PATH)
        df.index = pd.to_datetime(df.index)
        return df
    return build_extended_frame()


def load_ecmwf_features() -> pd.DataFrame | None:
    """Per (cell_id, date) ECMWF S2S ensemble mean/spread, or None if absent.

    Reforecast only: coverage stops at 2023-09-30, so a live run leaves these NaN and
    the boosters fall back on their native missing-value handling, as designed.
    """
    if not ECMWF_PATH.exists():
        return None
    df = pd.read_parquet(ECMWF_PATH)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _rain_climatology(train_years: tuple[int, int]) -> pd.DataFrame:
    lo, hi = train_years
    df = pd.read_parquet(FEATURES_PATH, columns=["cell_id", "sday", "year", "rain_1d"])
    df = df[(df["year"] >= lo) & (df["year"] <= hi)]
    df["dry"] = (df["rain_1d"] < DRY_DAY_THRESHOLD_MM).astype(float)
    return (df.groupby(["cell_id", "sday"])
              .agg(clim_rain_doy=("rain_1d", "mean"), clim_dryday_doy=("dry", "mean"))
              .reset_index())


def _onset_climatology(train_years: tuple[int, int]) -> pd.DataFrame:
    lo, hi = train_years
    ol = pd.read_parquet(ONSET_LABELS_PATH)
    ol = ol[(ol["year"] >= lo) & (ol["year"] <= hi)]
    return (ol.groupby("cell_id")
              .agg(clim_onset_doy=("onset_doy", "mean"),
                   clim_first_cand_doy=("first_cand_doy", "mean"),
                   clim_false_rate=("first_cand_failed", "mean"))
              .reset_index())


def apply_train_only_climatology(df: pd.DataFrame,
                                 train_years: tuple[int, int] = TRAIN_YEARS) -> pd.DataFrame:
    """Recompute the clim_* columns from train years only, as the boosters were fitted.

    features.parquet ships full-period 1991-2024 means, so a 2020-2024 row carries
    climatology computed partly from its own year. The XGBoost bundle was trained on
    train-only versions; feeding it the shipped ones inflates apparent skill. Requires
    `cell_id`, `sday` and `doy`. onset_threshold_mm is left alone - it has no year axis.
    """
    df = df.copy().drop(columns=CLIM_COLS)
    if CLIM_TRAIN_PATH.exists() and train_years == TRAIN_YEARS:
        df = df.merge(pd.read_parquet(CLIM_TRAIN_PATH), on=["cell_id", "sday"], how="left")
    else:
        df = df.merge(_rain_climatology(train_years), on=["cell_id", "sday"], how="left")
        df = df.merge(_onset_climatology(train_years), on="cell_id", how="left")
    # the shipped onset_doy_anom is doy minus clim_FIRST_CAND_doy, not clim_onset_doy
    df["onset_doy_anom"] = df["doy"] - df["clim_first_cand_doy"]
    return df


def attach(rows: pd.DataFrame, ecmwf: bool = True, clean_climatology: bool = True) -> pd.DataFrame:
    """Join every column the XGBoost bundle expects onto a cell-day frame.

    `rows` needs `date`; `cell_id`/`sday`/`doy` as well for ECMWF and clean climatology.
    Defaults match how the shipped models were trained - change them only to reproduce
    some other experiment.
    """
    if "date" not in rows.columns:
        raise KeyError("rows must carry a `date` column to join extended features")
    out = rows
    if clean_climatology:
        out = apply_train_only_climatology(out)
    out = out.join(extended_daily(), on="date")
    if ecmwf:
        ec = load_ecmwf_features()
        if ec is not None and "cell_id" in out.columns:
            out = out.merge(ec, on=["cell_id", "date"], how="left")
    return out
