"""The vendored XGBoost bundle scores identically here to how it was trained.

The load-bearing test is `test_reproduces_shipped_metrics`. If the feature pipeline ever
drifts from the training repo's, that is where it shows up, because the boosters are
frozen and their held-out numbers are recorded in the bundle.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import brier_score_loss, roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti.features import extended as EX  # noqa: E402
from varshadrishti.model import predict_xgb as PX  # noqa: E402

TEST_YEARS = (2020, 2024)


@pytest.fixture(scope="module")
def scored():
    df = pd.read_parquet(ROOT / "data" / "processed" / "features.parquet")
    df = EX.attach(df, ecmwf=True, clean_climatology=True)
    return df[df.year.between(*TEST_YEARS)]


def test_all_models_load():
    assert len(PX.available()) == 24
    for g in PX.GROUPS:
        for h in PX.HORIZONS:
            m = PX.load(f"y_{g}_{h}")
            assert m.metadata["target"] == f"y_{g}_{h}"
            assert len(m.features) == m.metadata["n_features"]
            assert 0.0 < m.threshold < 1.0


def test_target_dir_mapping():
    assert PX.target_dir("y_onset_21").name == "onset_21d"
    assert PX.target_dir("y_false_onset_7").name == "false_onset_7d"
    assert PX.target_dir("y_dry14_28").name == "dry14_28d"
    with pytest.raises(ValueError):
        PX.target_dir("onset_21")


def test_extended_frame_builds_every_column():
    ext = EX.build_extended_frame()
    assert set(EX.EXTENDED_FEATURES) <= set(ext.columns)
    # 10 indices x 3 transforms, 7 MJO derivatives, 4 horizons x cos/sin at valid time
    assert len(EX.EXTENDED_FEATURES) == 30 + 7 + 8


def test_clim_columns_are_train_only(scored):
    """The shipped clim_* are full-period means; the bundle needs train-years-only ones."""
    raw = pd.read_parquet(ROOT / "data" / "processed" / "features.parquet",
                          columns=["cell_id", "sday", "year", "clim_rain_doy"])
    raw = raw[raw.year.between(*TEST_YEARS)].reset_index(drop=True)
    assert not np.allclose(raw["clim_rain_doy"].to_numpy(),
                           scored["clim_rain_doy"].to_numpy()), \
        "attach() did not replace the leaky full-period climatology"


@pytest.mark.parametrize("target", ["y_onset_21", "y_dry14_28", "y_heavy_7"])
def test_reproduces_shipped_metrics(scored, target):
    """Scoring here must land exactly on the bundle's own held-out numbers."""
    m = PX.load(target)
    p = m.predict_proba(scored, strict=True)
    want = PX.metrics(target)["test"]
    y = scored[target].to_numpy(float)

    assert len(scored) == want["n"]
    assert roc_auc_score(y, p) == pytest.approx(want["roc_auc"], abs=1e-9)
    assert brier_score_loss(y, p) == pytest.approx(want["brier"], abs=1e-9)


def test_strict_mode_refuses_to_nan_fill(scored):
    m = PX.load("y_heavy_7")
    bad = scored.drop(columns=["olr_bob_anom_5d"])
    with pytest.raises(KeyError, match="olr_bob_anom_5d"):
        m.predict_proba(bad, strict=True)
    assert np.isfinite(m.predict_proba(bad, strict=False)).all()  # lenient path still runs


def test_hazard_curve_is_monotone(scored):
    haz = PX.onset_survival_curve(scored.head(500))
    cum = haz[["cum_week1", "cum_week2", "cum_week3", "cum_week4"]].to_numpy()
    assert (np.diff(cum, axis=1) >= -1e-12).all(), "survival chain must not decrease"
    assert ((cum >= 0) & (cum <= 1)).all()


def test_both_backends_fill_the_same_contract_slots():
    from varshadrishti.pipeline import infer as I

    rows = 8
    df = pd.read_parquet(ROOT / "data" / "processed" / "features.parquet").head(rows)
    df = EX.attach(df, ecmwf=True, clean_climatology=True)
    stat = I.statistical(df, backend="xgboost")

    assert list(stat.columns) == [f"{ev}_{lead}" for ev in I.EVENTS for lead in I.LEAD_ORDER]
    assert len(stat) == rows
    assert stat.notna().all().all(), "the bundle covers all 20 slots"
    v = stat.to_numpy()
    assert ((v >= 0) & (v <= 1)).all()


def test_unknown_backend_rejected():
    from varshadrishti.pipeline import infer as I

    with pytest.raises(ValueError, match="backend must be"):
        I.statistical(pd.DataFrame({"cell_id": ["x"]}), backend="catboost")
