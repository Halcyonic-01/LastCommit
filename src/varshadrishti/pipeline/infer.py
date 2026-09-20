"""Today's features -> P_stat, using the SAME builder the training set went through.

Nothing here recomputes a feature. `causal_features` and `FoldClimatology` are imported
from the training code, so a change to either moves training and inference together. The
one deliberate difference is the climatology: training uses fold-internal, inference uses
full-record, because at inference there is no held-out year to exclude.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..features import build as B
from ..features import labels as L
from ..features.climatology import CLIM_COLS
from ..features.indices import load_indices
from ..model import predict_xgb as PX

ROOT = Path(__file__).resolve().parents[3]

# contract event -> the trained target family
EVENTS = {"p_onset": "y_onset", "p_false_onset": "y_false_onset",
          "p_dry7": "y_dry7", "p_dry14": "y_dry14", "p_heavy": "y_heavy"}
LEAD_H = {"w1": 7, "w2": 14, "w3": 21, "w4": 28}

# The published backend. XGBoost fills all 20 contract slots; the LightGBM path is kept
# for comparison and for replaying the LOYO-validated numbers in models/metrics.json.
BACKEND = "xgboost"


def live_features(obs: pd.DataFrame, as_of: str, thresh: pd.Series,
                  clim: pd.DataFrame, extended: bool = True) -> pd.DataFrame:
    """One row per cell, for `as_of`. `obs` is recent observed rainfall (dates x cells)."""
    day = pd.Timestamp(as_of)
    if day not in obs.index:
        raise KeyError(f"{as_of} absent from observations ({obs.index.max().date()} latest)")

    feats = B.causal_features(obs, thresh.reindex(obs.columns).fillna(L.ONSET_FLOOR_MM))
    row = pd.DataFrame({name: frame.loc[day] for name, frame in feats.items()})
    row.index.name = "cell_id"
    row = row.reset_index()

    row["doy"] = day.dayofyear
    row["sday"] = (day - pd.Timestamp(day.year, *L.SEASON_START_MD)).days
    row = row.merge(clim, on="cell_id", how="left")
    row["onset_doy_anom"] = row["doy"] - row["clim_first_cand_doy"]
    row["onset_threshold_mm"] = row["cell_id"].map(thresh)

    idx = load_indices()
    near = idx.index[idx.index <= day]
    if len(near):
        for c in ("rmm1", "rmm2", "mjo_amp", "mjo_phase"):
            row[c] = idx.loc[near[-1], c]
    else:
        for c in ("rmm1", "rmm2", "mjo_amp", "mjo_phase"):
            row[c] = np.nan

    row["date"] = day
    if extended:
        from ..features import extended as EX

        # Train-only climatology, matching how the XGBoost bundle was fitted. ECMWF
        # reforecast stops at 2023, so a live run leaves those columns NaN by design.
        row = EX.attach(row, ecmwf=True, clean_climatology=True)
    return row


LEAD_ORDER = ["w1", "w2", "w3", "w4"]


def statistical(row: pd.DataFrame, backend: str = BACKEND) -> pd.DataFrame:
    """-> DataFrame indexed by cell_id, columns '<event>_<lead>', WINDOWED per lead week.

    The models are trained on CUMULATIVE targets ("within h days"), but P_nwp is windowed
    ("inside week k") and the app's four-week ribbon means per-week risk. Blending the two
    was averaging different events, and it showed: published p_dry7 rose monotonically
    0.351 -> 0.772 across the ribbon, which reads as "risk grows every week" and is just
    cumulation.

    The cumulative events are NESTED, so the windowed probability is exactly the
    difference of consecutive cumulative ones. No retraining needed. Each target is
    calibrated independently, so a difference can go slightly negative (1.5-4% of rows);
    clipped at zero.
    """
    if backend != "xgboost":
        raise ValueError(f"backend must be 'xgboost', got {backend!r}")
    have = {f"y_{g}_{h}" for g in PX.GROUPS for h in PX.HORIZONS}

    out = {}
    for ev, fam in EVENTS.items():
        cum = []
        for lead in LEAD_ORDER:
            t = f"{fam}_{LEAD_H[lead]}"
            cum.append(PX.predict(row, t) if t in have else np.full(len(row), np.nan))
        prev = np.zeros(len(row))
        for lead, c in zip(LEAD_ORDER, cum):
            out[f"{ev}_{lead}"] = np.clip(c - prev, 0.0, 1.0)
            prev = np.where(np.isnan(c), prev, c)
    df = pd.DataFrame(out, index=pd.Index(row["cell_id"], name="cell_id"))
    return df.clip(0.0, 1.0)


def feature_coverage(row: pd.DataFrame, backend: str = BACKEND) -> dict:
    """How much of each model's feature vector is actually populated for this run.

    Published, not just logged: the circulation indices stop at 2024-12-31 and the ECMWF
    reforecast at 2023-09-30, so a live run scores on a fraction of what the boosters were
    fitted on. A reader of the forecast is entitled to know that.
    """
    if backend != "xgboost":
        return {}
    worst = None
    for g in PX.GROUPS:
        for h in PX.HORIZONS:
            feats = PX.load(f"y_{g}_{h}").features
            live = sum(1 for f in feats if f in row.columns and row[f].notna().any())
            if worst is None or live / len(feats) < worst[1] / worst[2]:
                worst = (f"y_{g}_{h}", live, len(feats))
    target, live, total = worst
    return {"worst_case_model": target, "features_populated": live, "features_expected": total,
            "note": ("circulation indices end 2024-12-31 and ECMWF reforecast 2023-09-30; "
                     "absent columns are handled by XGBoost's native missing-value path")}


def missing_models() -> list[str]:
    """Which contract slots have no trained model behind them."""
    have = {f"y_{g}_{h}" for g in PX.GROUPS for h in PX.HORIZONS}
    return [f"{ev}_{lead}" for ev in EVENTS for lead, h in LEAD_H.items()
            if f"{EVENTS[ev]}_{h}" not in have]
