"""Leakage audit as executable tests.

Each one perturbs an input and asserts what may and may not move. A leak that survives
code review dies here, because the test does not read the code - it pokes the data.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti.features import labels as L  # noqa: E402
from varshadrishti.features.climatology import (  # noqa: E402
    CLIM_COLS, FoldClimatology, reference_from_fold)

PROC = ROOT / "data" / "processed"
YEARS = list(range(2000, 2010))


def toy_rain(years=YEARS, cells=5, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{min(years)}-01-01", f"{max(years)}-12-31", freq="D")
    cols = [f"imd:{10+i}:{75+i}" for i in range(cells)]
    x = np.zeros((len(idx), cells))
    m = (idx.month >= 6) & (idx.month <= 9)
    x[m] = rng.gamma(1.2, 6.0, size=(m.sum(), cells))
    return pd.DataFrame(x, index=idx, columns=cols)


def toy_rows(rain, years=YEARS):
    out = []
    for y in years:
        s = L._season_slice(rain, y)
        for c in rain.columns:
            out.append(pd.DataFrame({
                "year": y, "cell_id": c,
                "date": s.index,
                "sday": (s.index - pd.Timestamp(y, 6, 1)).days,
                "doy": s.index.dayofyear,
                "y_t": (s[c].to_numpy() < L.RAINY_DAY_MM).astype(float),
            }))
    return pd.concat(out, ignore_index=True)


def toy_onset(rain, years=YEARS):
    t = L.wet_spell_threshold(rain, years)
    return pd.concat([L.season_labels(rain, y, t) for y in years], ignore_index=True)


@pytest.fixture(scope="module")
def toy():
    rain = toy_rain()
    rows = toy_rows(rain)
    fc = FoldClimatology(rain, YEARS, toy_onset(rain), rows)
    return rain, rows, fc


# --- the held-out year may not reach ANY row's features --------------------


def test_a_folds_climatology_ignores_the_held_out_year_entirely(toy):
    """The bug this closes: per-ROW LOYO climatology let a 1995 training row carry
    climatology that included the held-out 2010, ~1/33 of it. Under fold climatology,
    rewriting the held-out year must change nothing anywhere in that fold."""
    rain, rows, fc = toy
    hold = YEARS[4]
    before = fc.for_fold(hold)

    bad = rain.copy()
    bad.loc[f"{hold}-06-01":f"{hold}-09-30"] = 500.0
    fc2 = FoldClimatology(bad, YEARS, toy_onset(bad), rows)
    after = fc2.for_fold(hold)

    for c in ("clim_rain_doy", "clim_dryday_doy"):
        np.testing.assert_allclose(
            before[c].to_numpy(), after[c].to_numpy(), rtol=1e-6,
            err_msg=f"{c} moved for EVERY row when only the held-out year changed")


def test_a_training_row_in_one_fold_still_sees_other_years(toy):
    """The mirror: if nothing ever moved, the climatology would be a constant, not a
    climatology. Changing a year that is NOT held out must move that fold's features."""
    rain, rows, fc = toy
    hold = YEARS[4]
    other = YEARS[2]
    before = fc.for_fold(hold)

    bad = rain.copy()
    bad.loc[f"{other}-06-01":f"{other}-09-30"] = 500.0
    after = FoldClimatology(bad, YEARS, toy_onset(bad), rows).for_fold(hold)
    assert not np.allclose(before["clim_rain_doy"], after["clim_rain_doy"]), \
        "a non-held-out year changed and the fold's climatology did not move"


def test_every_fold_gets_a_different_climatology(toy):
    """If two folds shared one climatology, one of them was fitted on its own test year."""
    _, _, fc = toy
    seen = {}
    for h in YEARS:
        key = float(fc.for_fold(h)["clim_rain_doy"].sum())
        assert key not in seen, f"fold {h} has the same climatology as fold {seen[key]}"
        seen[key] = h


def test_the_bss_reference_is_built_from_training_years_only(toy):
    """The bar we clear must not have seen the year it grades."""
    rain, rows, _ = toy
    hold = YEARS[3]
    before = reference_from_fold(rows, "y_t", hold, YEARS)

    bad = rows.copy()
    m = (bad.year == hold).to_numpy()
    bad.loc[m, "y_t"] = 1.0
    after = reference_from_fold(bad, "y_t", hold, YEARS)
    np.testing.assert_allclose(before, after, rtol=1e-9,
                               err_msg="the reference moved when only the graded year changed")


def test_the_reference_does_move_when_a_training_year_changes(toy):
    rain, rows, _ = toy
    hold = YEARS[3]
    before = reference_from_fold(rows, "y_t", hold, YEARS)
    bad = rows.copy()
    bad.loc[(bad.year == YEARS[1]).to_numpy(), "y_t"] = 1.0
    assert not np.allclose(before, reference_from_fold(bad, "y_t", hold, YEARS))


# --- the static feature table must not smuggle climatology in --------------


@pytest.mark.skipif(not (PROC / "features.parquet").exists(), reason="build features first")
def test_training_overwrites_the_parquets_climatology_columns():
    """features.parquet still carries clim_* for INFERENCE. If a training run read those
    instead of the fold's, the leak would be back with no visible symptom."""
    src = (ROOT / "scripts" / "exp_p5b.py").read_text()
    assert "fc.for_fold(hold)" in src, "the fold climatology is never built"
    assert "X[use_clim] =" in src, "fold climatology is never written over the static columns"


@pytest.mark.skipif(not (PROC / "features.parquet").exists(), reason="build features first")
def test_no_target_column_can_reach_the_feature_matrix():
    from varshadrishti.model import train as T  # noqa: PLC0415

    df = pd.read_parquet(PROC / "features.parquet")
    feats = T.feature_names(df)
    assert not [c for c in feats if c.startswith("y_")], "a target is in the feature list"
    assert "date" not in feats and "cell_id" not in feats and "year" not in feats


@pytest.mark.skipif(not (PROC / "features.parquet").exists(), reason="build features first")
def test_the_fold_climatology_covers_every_row_of_the_real_table():
    """A silent reindex failure would fill training rows with NaN and look like weak skill."""
    from varshadrishti.data.rainfall import load_imd  # noqa: PLC0415

    df = pd.read_parquet(PROC / "features.parquet")
    onset = pd.read_parquet(PROC / "onset_labels.parquet")
    years = sorted(df.year.unique())
    w = pd.read_parquet(PROC / "weights_imd_hoblis.parquet")
    pad = 0.3
    b = (w.lon.min() - pad, w.lat.min() - pad, w.lon.max() + pad, w.lat.max() + pad)
    rain = load_imd(min(years), max(years), bounds=b)
    rain = rain[[c for c in sorted(set(w.cell_id)) if c in rain.columns]]

    fc = FoldClimatology(rain, years, onset, df)
    got = fc.for_fold(years[10])
    assert len(got) == len(df)
    assert list(got.columns) == CLIM_COLS
    assert got.notna().all().all(), f"NaN in fold climatology: {got.isna().sum().to_dict()}"


# --- the shipped model must be the one we measured -------------------------

MODELS = ROOT / "models"


@pytest.mark.skipif(not list(MODELS.glob("y_*.txt")), reason="run scripts/train_model.py")
def test_no_shipped_model_uses_the_year_label_features():
    """P5b measured oni/dmi/nino34_anom as REMOVING skill — paired P(worse) 0.005 and
    0.001 on onset and heavy rain. If one creeps back into a shipped booster we are
    deploying a model we have evidence is worse."""
    import lightgbm as lgb  # noqa: PLC0415

    from varshadrishti.model import train as T  # noqa: PLC0415

    for f in sorted(MODELS.glob("y_*.txt")):
        names = set(lgb.Booster(model_file=str(f)).feature_name())
        bad = names & T.EXCLUDED
        assert not bad, f"{f.name} was trained on {sorted(bad)}"


@pytest.mark.skipif(not list(MODELS.glob("y_*.txt")), reason="run scripts/train_model.py")
def test_the_shipped_model_saw_the_climatology_inference_will_give_it():
    """Training on fold climatology while serving full-record climatology leaves live
    features systematically offset from the ones the model learned."""
    src = (ROOT / "scripts" / "train_model.py").read_text()
    assert "fc.for_inference()" in src, "the final fit does not use full-record climatology"
    assert "fit_final(df_ship" in src, "the final fit still reads the fold-climatology frame"


@pytest.mark.skipif(not (MODELS / "metrics.json").exists(), reason="run scripts/train_model.py")
def test_the_recorded_config_matches_what_p5b_validated():
    from varshadrishti.model import train as T  # noqa: PLC0415

    assert T.PARAMS["subsample"] == 0.6 and T.PARAMS["colsample_bytree"] == 0.6, (
        "bagging-by-year was the regularisation P5b measured; PARAMS no longer match")
