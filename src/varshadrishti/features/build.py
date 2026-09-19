"""Assemble the per-cell per-day training table.

Two rules govern every column here, and the tests enforce both:

  CAUSAL   a feature may only use rain up to and including today. The confirmed onset
           date needs 30 days of hindsight, so it can never be a feature - only the
           wet-spell CANDIDATE, which is knowable the morning it completes.
  LEAVE-ONE-YEAR-OUT  climatology features for year Y are computed from the other 33
           seasons. Fitted on all 34 they quietly leak the held-out year into its own
           prediction, and no shuffled-label test would catch it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import labels as L
from .indices import load_indices

BACK_WINDOWS = (1, 3, 7, 14, 30)
HORIZONS = (7, 14, 21, 28)
INDEX_COLS = ["oni", "dmi", "nino34_anom", "rmm1", "rmm2", "mjo_amp", "mjo_phase"]


def _days_since_rain(wet: pd.DataFrame) -> pd.DataFrame:
    """Days since the last rainy day, counting from the season start."""
    idx = np.arange(len(wet))[:, None]
    last = np.where(wet.to_numpy(), idx, -1)
    last = pd.DataFrame(last, index=wet.index, columns=wet.columns).cummax()
    return pd.DataFrame(idx - last.to_numpy(), index=wet.index, columns=wet.columns).clip(0, 99)


def causal_features(season: pd.DataFrame, thresh: pd.Series) -> dict[str, pd.DataFrame]:
    """Backward-looking only. Everything here is knowable by the evening of that day."""
    wet = season >= L.RAINY_DAY_MM
    f = {f"rain_{w}d": season.rolling(w, min_periods=1).sum() for w in BACK_WINDOWS}
    f["wet_days_30d"] = wet.rolling(30, min_periods=1).sum()
    f["days_since_rain"] = _days_since_rain(wet)

    # The onset CANDIDATE: a 5-day spell clearing the local bar, closing today.
    five = season.rolling(L.WET_WINDOW_DAYS).sum()
    rainy5 = wet.rolling(L.WET_WINDOW_DAYS).sum()
    cand = (five.ge(thresh, axis=1) & (rainy5 >= L.WET_WINDOW_RAINY)).fillna(False)
    f["wet_spell_today"] = cand.astype(float)
    f["wet_spell_seen"] = cand.cummax().astype(float)
    f["days_since_wet_spell"] = _days_since_rain(cand)
    f["spell_deficit"] = five.sub(thresh, axis=1)  # how far short of the local bar
    return f


def loyo_climatology(rain: pd.DataFrame, years, onset: pd.DataFrame) -> dict:
    """Per (cell, day-of-year) climatology holding out each year in turn."""
    # Keyed on days since 1 Jun, never day-of-year: a leap year shifts every doy by one,
    # so doy-keyed climatology silently fails to match at the season edges.
    doy_rain, doy_dry = {}, {}
    for y in years:
        s = L._season_slice(rain, y)
        sd = (s.index - pd.Timestamp(y, *L.SEASON_START_MD)).days
        doy_rain[y] = s.set_index(pd.Index(sd, name="sday"))
        doy_dry[y] = (s < L.RAINY_DAY_MM).set_index(pd.Index(sd, name="sday"))

    out = {}
    for y in years:
        others = [o for o in years if o != y]
        rain_sum = sum(doy_rain[o] for o in others) / len(others)
        dry_sum = sum(doy_dry[o] for o in others) / len(others)
        o = onset[onset.year.isin(others)].groupby("cell_id")
        out[y] = {"clim_rain_doy": rain_sum, "clim_dryday_doy": dry_sum,
                  "clim_onset_doy": o["onset_doy"].mean(),
                  "clim_first_cand_doy": o["first_cand_doy"].mean(),
                  "clim_false_rate": o["first_cand_failed"].mean()}
    return out


def targets(rain: pd.DataFrame, season_idx: pd.DatetimeIndex, thresh: pd.Series) -> dict:
    """Forward-looking answers. Built on the FULL record so a late-September window
    can still see into October rather than being silently truncated to False."""
    ev = L.daily_event_labels(rain)
    out = {}
    for h in (7, 14):
        out[f"y_dry7_{h}"] = L.within_horizon(ev["dry7_starts"], h).loc[season_idx]
        out[f"y_dry14_{h}"] = L.within_horizon(ev["dry14_starts"], h).loc[season_idx]
    out["y_heavy_7"] = L.within_horizon(ev["heavy"], 7).loc[season_idx]

    five = rain.rolling(L.WET_WINDOW_DAYS).sum()
    rainy5 = (rain >= L.RAINY_DAY_MM).rolling(L.WET_WINDOW_DAYS).sum()
    cand = (five.ge(thresh, axis=1) & (rainy5 >= L.WET_WINDOW_RAINY)).fillna(False)
    for h in HORIZONS:
        out[f"y_onset_{h}"] = L.within_horizon(cand, h).loc[season_idx]
    return out


def build_year(rain: pd.DataFrame, year: int, thresh: pd.Series, clim: dict,
               onset_row: pd.DataFrame, idx: pd.DataFrame) -> pd.DataFrame:
    season = L._season_slice(rain, year)
    feats = causal_features(season, thresh)
    tgts = targets(rain, season.index, thresh)

    long = []
    for name, frame in {**feats, **tgts}.items():
        long.append(frame.stack().rename(name))
    df = pd.concat(long, axis=1).reset_index()
    df.columns = ["date", "cell_id"] + list(df.columns[2:])

    df["year"] = year
    df["doy"] = df["date"].dt.dayofyear
    df["sday"] = (df["date"] - pd.Timestamp(year, *L.SEASON_START_MD)).dt.days

    c = clim[year]
    for key in ("clim_rain_doy", "clim_dryday_doy"):
        flat = c[key].stack().rename(key).reset_index()
        flat.columns = ["sday", "cell_id", key]
        df = df.merge(flat, on=["sday", "cell_id"], how="left")
    for k in ("clim_onset_doy", "clim_first_cand_doy", "clim_false_rate"):
        df[k] = df["cell_id"].map(c[k])
    df["onset_doy_anom"] = df["doy"] - df["clim_first_cand_doy"]

    df = df.merge(idx, left_on="date", right_index=True, how="left")
    df["onset_threshold_mm"] = df["cell_id"].map(thresh)
    return df


def build(rain: pd.DataFrame, years, progress=print) -> tuple[pd.DataFrame, pd.DataFrame]:
    years = list(years)
    thresh = L.wet_spell_threshold(rain, years)
    onset = pd.concat([L.season_labels(rain, y, thresh) for y in years], ignore_index=True)
    clim = loyo_climatology(rain, years, onset)
    idx = load_indices()[INDEX_COLS]

    frames = []
    for y in years:
        frames.append(build_year(rain, y, thresh, clim, onset, idx))
        progress(f"  {y}  {len(frames[-1]):>7,} rows")
    return pd.concat(frames, ignore_index=True), onset
