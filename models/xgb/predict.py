"""Load and run VarshaDrishti's monsoon event models.

No dependency on the training repo -- only xgboost + pandas/numpy. Each model
directory (events/<event>_<horizon>d/ or onset_hazard/week{1..4}/) is fully
self-contained: model.json (the trained booster), features.json (the exact,
ordered feature list the model expects), metadata.json (decision threshold,
hyperparameters, training provenance).

Usage:
    from predict import EventModel

    model = EventModel.load("events/onset_21d")
    prob = model.predict_proba(row)          # row: dict or 1-row DataFrame
    is_event = model.predict(row)            # uses the model's own tuned threshold

    # onset hazard survival curve (the more informative onset output --
    # see the project report for why this beats the plain cumulative targets
    # at long lead):
    from predict import onset_survival_curve
    curve = onset_survival_curve("onset_hazard", row)
    # -> {"week1": p, "week2": p, "week3": p, "week4": p,
    #     "cumulative_by_week": {...}, "hazard_week4_reliable": False}

Missing features (e.g. ecmwf_* columns outside the 2004-2023/season-date
coverage window, or any field you don't have) can be left out of `row` or set
to None/NaN -- XGBoost's native missing-value handling takes it from there.
This matters most for the `onset` event models and hazard weeks 1-3, which
use ECMWF S2S features that are only populated on real ECMWF cycle dates.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

HERE = Path(__file__).resolve().parent


class EventModel:
    def __init__(self, booster: xgb.XGBClassifier, features: list[str], metadata: dict):
        self.booster = booster
        self.features = features
        self.metadata = metadata
        self.threshold = metadata["decision_threshold"]

    @classmethod
    def load(cls, model_dir: str | Path) -> "EventModel":
        model_dir = Path(model_dir)
        if not model_dir.is_absolute():
            model_dir = HERE / model_dir
        booster = xgb.XGBClassifier()
        booster.load_model(model_dir / "model.json")
        features = json.loads((model_dir / "features.json").read_text())
        metadata = json.loads((model_dir / "metadata.json").read_text())
        return cls(booster, features, metadata)

    def _to_frame(self, row) -> pd.DataFrame:
        if isinstance(row, dict):
            row = pd.DataFrame([row])
        elif isinstance(row, pd.Series):
            # A Series transposed to a 1-row frame collapses every column to
            # object dtype if the source Series was itself mixed-type (e.g. a
            # row pulled straight from a DataFrame with string id columns
            # alongside numeric ones) -- must re-cast per column afterward.
            row = row.to_frame().T
        missing = [f for f in self.features if f not in row.columns]
        for f in missing:
            row[f] = np.nan
        out = row[self.features].apply(pd.to_numeric, errors="coerce")
        return out

    def predict_proba(self, row) -> np.ndarray:
        """P(event) for each input row. `row`: dict, pandas Series, or DataFrame."""
        X = self._to_frame(row)
        return self.booster.predict_proba(X)[:, 1]

    def predict(self, row) -> np.ndarray:
        """Binary call using this model's own validation-tuned threshold
        (NOT 0.5 -- see metadata['decision_threshold'])."""
        return (self.predict_proba(row) >= self.threshold).astype(int)


def onset_survival_curve(hazard_dir: str | Path, row) -> dict:
    """Load all 4 onset_hazard/week* models and combine them into:
      - per-week conditional hazard (P(onset this week | not yet occurred))
      - cumulative P(onset by end of week k) via the survival chain
    Week 4's model does NOT use ECMWF (proven not to help there -- see the
    project report); its skill is close to random (AUC ~0.55) and its output
    should be treated as low-confidence, flagged accordingly below.
    """
    hazard_dir = Path(hazard_dir)
    if not hazard_dir.is_absolute():
        hazard_dir = HERE / hazard_dir

    weekly = {}
    survival = 1.0
    cumulative = {}
    for week in ["week1", "week2", "week3", "week4"]:
        m = EventModel.load(hazard_dir / week)
        p = float(m.predict_proba(row)[0])
        weekly[week] = p
        survival *= (1 - p)
        cumulative[week] = 1 - survival

    return {
        **weekly,
        "cumulative_by_week": cumulative,
        "hazard_week4_reliable": False,  # AUC ~0.55 on held-out test years; treat as near-uninformative
    }
