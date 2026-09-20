"""ENSO / IOD / MJO context, each used at the timescale where it measurably works.

PS 26086 asks for global boundary conditions paired with regional data. All three indices
are ingested. What we measured over our own 34 Karnataka seasons decides where each is
allowed to act:

  MJO   sub-seasonal. The single largest feature win (+0.018 to +0.019 BSS). It varies
        DAILY, so 34 seasons is 4,148 observations, not 34. It is in the model.
  ENSO  CONCURRENT, not predictive. corr(ONI, season rainfall anomaly) = -0.39 sounds
        like seasonal skill and is not: indices.py lags monthly values 32 days, which is a
        correct PUBLICATION lag but not a FORECAST lag, so during Jun-Sep the oni column
        carries May-August ONI — the state of the very season being described. Measured
        with strictly pre-monsoon windows the correlation collapses: DJF +0.032, MAM
        -0.046. So ENSO tells you what kind of season you are IN, never what is coming.
        It also cannot improve 1-4 week timing — added to the model it costs skill at
        every lead, to P(worse) = 1.000. Reported as context, never fed to the forecast.
  IOD   neither. corr(DMI, season anomaly) = +0.07, r-squared 0.005, and harmful
        sub-seasonally. Reported with its own null result rather than quietly dropped.

The distinction that keeps this honest: stating what El Nino seasons DID is a fact about
34 years. Saying what this season WILL do is a forecast, and our seasonal-anomaly skill is
nil (per-season bias 0.055 against climatology's 0.064). This module only ever does the
former, and it is aimed at extension officers - the PS's second user - not at a farmer
deciding whether to sow this week.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROC = ROOT / "data" / "processed"

EL_NINO = 0.5      # NOAA's ONI threshold
LA_NINA = -0.5


def phase(oni: float) -> str:
    if oni >= EL_NINO:
        return "el_nino"
    if oni <= LA_NINA:
        return "la_nina"
    return "neutral"


def historical_effect(features: pd.DataFrame | None = None) -> dict:
    """What each ENSO phase DID to Karnataka rainfall across our 34 seasons."""
    df = features if features is not None else pd.read_parquet(
        PROC / "features.parquet", columns=["year", "rain_1d", "oni", "y_dry7_7"])
    g = (df.groupby("year")
           .agg(season_mm=("rain_1d", "mean"), oni=("oni", "mean"),
                dry_rate=("y_dry7_7", "mean")))
    g["season_mm"] *= 122
    g["anom_pct"] = 100 * (g.season_mm / g.season_mm.mean() - 1)
    g["phase"] = [phase(v) for v in g.oni]

    out = {}
    for ph, sub in g.groupby("phase"):
        out[ph] = {
            "seasons": int(len(sub)),
            "mean_anomaly_pct": round(float(sub.anom_pct.mean()), 1),
            "dry_spell_rate": round(float(sub.dry_rate.mean()), 3),
        }
    out["_correlation"] = round(float(g.oni.corr(g.anom_pct)), 3)
    return out


def current(as_of: str, indices: pd.DataFrame | None = None) -> dict:
    """Today's ENSO/IOD state plus the measured historical association. Context only."""
    from ..features.indices import load_indices

    idx = indices if indices is not None else load_indices()
    day = pd.Timestamp(as_of)
    # ONI is monthly and published in arrears, so the newest valid value can be weeks
    # old. Take the last one that EXISTS rather than the last row, or a normal
    # publication lag reads as "no ENSO data".
    upto = idx.loc[:day]
    if upto.empty or upto["oni"].last_valid_index() is None:
        return {}
    oni = float(upto["oni"].loc[upto["oni"].last_valid_index()])
    row = upto.iloc[-1]

    ph = phase(oni)
    hist = historical_effect()
    seen = hist.get(ph, {})
    return {
        "enso_phase": ph,
        "oni": round(oni, 2),
        "dmi": None if pd.isna(row.get("dmi")) else round(float(row["dmi"]), 2),
        "basis": (f"{seen.get('seasons', 0)} of 34 seasons since 1991 were {ph}; "
                  f"they averaged {seen.get('mean_anomaly_pct', 0):+.1f}% rainfall "
                  f"with a dry-spell rate of {seen.get('dry_spell_rate', 0):.2f}."),
        "is_forecast": False,
        "is_concurrent": True,
        "note": ("Concurrent description of the season in progress, not a prediction of "
                 "it. The -0.39 association with season rainfall is measured against ONI "
                 "from the SAME season; with strictly pre-monsoon ONI it is +0.03, i.e. "
                 "absent. ENSO does not improve 1-4 week timing either, so it is excluded "
                 "from the model. IOD shows no association at all (r = +0.07)."),
        # P5b: corr(model skill, ONI) = -0.32. The worst seasons on record for this model
        # were 2015, 2023, 2019, 2017 — El Nino and positive-IOD years. An officer reading
        # a forecast in a strong El Nino should know it is our weakest regime.
        "model_reliability": ("reduced" if ph == "el_nino" else "typical"),
        "reliability_basis": ("Measured: forecast skill correlates -0.32 with ONI. The "
                              "model's four worst seasons were El Nino or positive-IOD "
                              "years." if ph == "el_nino" else
                              "Skill in this phase is in line with the 34-season average."),
    }
