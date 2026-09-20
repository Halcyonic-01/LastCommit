"""Load and score the vendored XGBoost bundle in models/xgb.

Mirrors model/predict.py's shape so either backend can sit behind the same call. Two
differences are real and deliberate, not oversights:

  NO CALIBRATION MAP. The LightGBM boosters ship an out-of-fold isotonic map replayed
  with np.interp; these ship a validation-tuned `decision_threshold` and raw
  binary:logistic probabilities. Nothing here re-calibrates.
  DIFFERENT VALIDATION PROTOCOL. These were fitted on a chronological split
  (train 1991-2015, val 2016-2019, test 2020-2024), not 34-fold leave-one-year-out, so
  their metrics are not comparable with models/metrics.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
XGB_DIR = ROOT / "models" / "xgb"

# contract event family -> the bundle's directory prefix
GROUPS = ("onset", "false_onset", "dry7", "dry14", "heavy")
HORIZONS = (7, 14, 21, 28)


def available() -> list[str]:
    """Every loadable model, as bundle-relative paths."""
    return sorted(str(p.parent.relative_to(XGB_DIR))
                  for p in XGB_DIR.rglob("model.json"))


def target_dir(target: str) -> Path:
    """`y_onset_21` -> models/xgb/events/onset_21d."""
    if not target.startswith("y_"):
        raise ValueError(f"expected a y_<group>_<h> target, got {target!r}")
    stem = target[2:]
    group, _, h = stem.rpartition("_")
    return XGB_DIR / "events" / f"{group}_{h}d"


class EventModel:
    """One booster plus the exact ordered feature list it was fitted on."""

    def __init__(self, booster, features: list[str], metadata: dict):
        self.booster = booster
        self.features = features
        self.metadata = metadata
        self.threshold = metadata["decision_threshold"]

    @classmethod
    def load(cls, model_dir: str | Path) -> "EventModel":
        import xgboost as xgb

        model_dir = Path(model_dir)
        if not model_dir.is_absolute():
            model_dir = XGB_DIR / model_dir
        booster = xgb.XGBClassifier()
        booster.load_model(model_dir / "model.json")
        return cls(booster,
                   json.loads((model_dir / "features.json").read_text()),
                   json.loads((model_dir / "metadata.json").read_text()))

    def _frame(self, rows, strict: bool) -> pd.DataFrame:
        if isinstance(rows, dict):
            rows = pd.DataFrame([rows])
        elif isinstance(rows, pd.Series):
            rows = rows.to_frame().T
        missing = [f for f in self.features if f not in rows.columns]
        if missing and strict:
            raise KeyError(f"{self.metadata.get('target')}: missing feature columns {missing}")
        if missing:
            rows = rows.assign(**{f: np.nan for f in missing})
        return rows[self.features].apply(pd.to_numeric, errors="coerce")

    def predict_proba(self, rows, strict: bool = False) -> np.ndarray:
        """P(event) per row. strict=True refuses to silently NaN-fill a missing column."""
        return self.booster.predict_proba(self._frame(rows, strict))[:, 1]

    def predict(self, rows, strict: bool = False) -> np.ndarray:
        """Binary call at this model's own tuned threshold, which is not 0.5."""
        return (self.predict_proba(rows, strict) >= self.threshold).astype(int)


def load(target: str) -> EventModel:
    """Load by the project's target name, e.g. `y_dry7_14`."""
    return EventModel.load(target_dir(target))


def predict(df: pd.DataFrame, target: str, strict: bool = False) -> np.ndarray:
    """Probability for `target`, one value per row of `df`."""
    return load(target).predict_proba(df, strict)


def predict_all(df: pd.DataFrame, strict: bool = False) -> pd.DataFrame:
    """Every event target at once, as columns beside the rows you passed in."""
    targets = [f"y_{g}_{h}" for g in GROUPS for h in HORIZONS]
    return pd.DataFrame({t: predict(df, t, strict) for t in targets}, index=df.index)


def onset_survival_curve(rows, strict: bool = False) -> pd.DataFrame:
    """Per-week conditional onset hazard chained into a cumulative survival curve.

    -> columns week1..week4 (hazard) and cum_week1..cum_week4. Week 4 scored AUC ~0.55
    on held-out years, so it is published as low-confidence, not as signal.
    """
    if isinstance(rows, dict):
        rows = pd.DataFrame([rows])
    out = pd.DataFrame(index=rows.index)
    survival = np.ones(len(rows))
    for wk in ("week1", "week2", "week3", "week4"):
        p = EventModel.load(XGB_DIR / "onset_hazard" / wk).predict_proba(rows, strict)
        out[wk] = p
        survival = survival * (1 - p)
        out[f"cum_{wk}"] = 1 - survival
    return out


def metrics(target: str) -> dict:
    """The bundle's own held-out metrics for one target."""
    return json.loads((target_dir(target) / "metrics.json").read_text())
