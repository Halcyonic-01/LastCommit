"""Load the shipped models and score rows. No training, no sklearn needed at inference."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "models"


def available() -> list[str]:
    return sorted(p.stem for p in MODELS.glob("y_*.txt"))


def load(target: str, models_dir: Path = MODELS):
    """-> (booster, calibration). The calibration is two arrays, applied with np.interp."""
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(models_dir / f"{target}.txt"))
    z = np.load(models_dir / f"{target}_isotonic.npz")
    return booster, (z["x"], z["y"])


def predict(df: pd.DataFrame, target: str, models_dir: Path = MODELS) -> np.ndarray:
    """Calibrated probability for `target`, one value per row of `df`.

    `df` needs the columns the model was trained on — build them with
    scripts/build_features.py. Extra columns are ignored; a missing one raises.
    """
    booster, (cx, cy) = load(target, models_dir)
    need = booster.feature_name()
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise KeyError(f"{target}: missing feature columns {missing}")
    raw = booster.predict(df[need])
    return np.interp(raw, cx, cy)  # isotonic replayed without sklearn


def predict_all(df: pd.DataFrame, models_dir: Path = MODELS) -> pd.DataFrame:
    """Every shipped target at once, as columns beside the rows you passed in."""
    return pd.DataFrame(
        {t: predict(df, t, models_dir) for t in available()}, index=df.index
    )
