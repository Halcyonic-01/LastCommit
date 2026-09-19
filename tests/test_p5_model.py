"""P5 acceptance: leave-one-year-out training, isotonic calibration, skill vs climatology.

The claim this phase makes is "better than knowing the local climate". Three things could
make that claim false without any error being raised — a fold that trains on its own test
year, a climatology reference that has seen the year it grades, and a calibration map
fitted on the predictions it is scoring. Each has a test that perturbs the data and checks
what moves.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti.model import metrics as M  # noqa: E402
from varshadrishti.model import train as T  # noqa: E402

MODELS = ROOT / "models"
METRICS = MODELS / "metrics.json"
PROC = ROOT / "data" / "processed"

LEAD12 = ["y_dry7_7", "y_dry7_14", "y_onset_7", "y_onset_14"]


def toy(years=8, cells=6, days=60, seed=0):
    """A tiny panel with a real signal: the target follows a lagged feature plus noise."""
    rng = np.random.default_rng(seed)
    rows = []
    for y in range(2000, 2000 + years):
        for c in range(cells):
            x = rng.normal(0, 1, days)
            # The cell effect is NORMALISED, not 0.3*c: with 12 cells the raw form spans
            # base rates 0.27-0.91, which per-cell climatology predicts almost perfectly
            # while the model (no cell feature) cannot — the positive control then fails
            # for a reason that has nothing to do with what the test is checking.
            cell_effect = 1.2 * (c / max(1, cells - 1) - 0.5)
            p = 1 / (1 + np.exp(-(0.9 * x + cell_effect - 0.3)))
            rows.append(pd.DataFrame({
                "year": y, "cell_id": f"c{c}", "sday": np.arange(days),
                "date": pd.date_range(f"{y}-06-01", periods=days),
                "f1": x, "f2": rng.normal(0, 1, days),
                "y_t": rng.binomial(1, p).astype(float),
            }))
    return pd.concat(rows, ignore_index=True)


# --- metrics are right ------------------------------------------------------


def test_brier_and_auc_match_scikit_learn():
    from sklearn.metrics import brier_score_loss, roc_auc_score

    rng = np.random.default_rng(1)
    y = rng.binomial(1, 0.3, 5000).astype(float)
    p = np.clip(rng.beta(2, 5, 5000), 1e-6, 1 - 1e-6)
    assert M.brier(y, p) == pytest.approx(brier_score_loss(y, p), abs=1e-12)
    assert M.roc_auc(y, p) == pytest.approx(roc_auc_score(y, p), abs=1e-9)


def test_bss_is_zero_for_the_reference_itself():
    rng = np.random.default_rng(2)
    y = rng.binomial(1, 0.4, 2000).astype(float)
    ref = np.full(2000, 0.4)
    assert M.bss(y, ref, ref) == pytest.approx(0.0, abs=1e-12)


def test_bss_is_one_for_a_perfect_forecast():
    y = np.array([0.0, 1.0, 1.0, 0.0])
    assert M.bss(y, y, np.full(4, 0.5)) == pytest.approx(1.0)


def test_murphy_decomposition_reconstructs_the_brier_score():
    rng = np.random.default_rng(3)
    y = rng.binomial(1, 0.35, 20000).astype(float)
    p = np.clip(0.35 + 0.3 * (y - 0.35) + rng.normal(0, 0.1, 20000), 0.001, 0.999)
    # The decomposition is exact only when grouping by unique forecast values, so the
    # residual must SHRINK as the bins get finer. A constant residual would mean the
    # formula is wrong rather than merely binned.
    coarse = M.murphy(y, p, bins=10)
    fine = M.murphy(y, p, bins=2000)
    bs = M.brier(y, p)
    r_coarse = abs(coarse["reliability"] - coarse["resolution"] + coarse["uncertainty"] - bs)
    r_fine = abs(fine["reliability"] - fine["resolution"] + fine["uncertainty"] - bs)
    assert r_fine < r_coarse / 5, f"residual did not shrink with bins: {r_coarse:.2e} -> {r_fine:.2e}"
    assert r_fine < 1e-4, f"decomposition does not reconstruct BS even at 2000 bins: {r_fine:.2e}"


def test_the_year_bootstrap_resamples_years_not_rows():
    """A row bootstrap on 1.3 M correlated rows returns an interval far too narrow."""
    rng = np.random.default_rng(4)
    n = 4000
    groups = np.repeat(np.arange(20), n // 20)
    y = rng.binomial(1, 0.3, n).astype(float)
    p = np.clip(rng.beta(2, 5, n), 1e-6, 1 - 1e-6)
    ref = np.full(n, 0.3)
    lo, hi = M.block_bootstrap_bss(y, p, ref, groups, n_boot=200)
    assert lo < M.bss(y, p, ref) < hi
    assert hi - lo > 1e-4, "interval collapsed — groups are being ignored"


# --- the three ways this could silently lie ---------------------------------


def test_no_fold_is_ever_trained_on_the_year_it_predicts():
    years = sorted(toy().year.unique())
    for fold, hold in enumerate(years):
        tr = [y for y in years if y != hold]
        val = T._inner_val_years(tr, fold)
        fit = [y for y in tr if y not in val]
        assert hold not in val, f"fold {hold}: early stopping validates on the test year"
        assert hold not in fit, f"fold {hold}: trained on the test year"
        assert fit and val, f"fold {hold}: empty split {fit=} {val=}"


def test_the_inner_split_never_starves_the_fit():
    """A flat 3 validation years out of 5 leaves 2 to fit on and the model loses for
    want of data, not for cause."""
    for n in (5, 8, 12, 34):
        tr = list(range(n - 1))
        val = T._inner_val_years(tr, 0)
        assert len(tr) - len(val) >= max(2, len(tr) // 2), f"{n} years: only {len(tr)-len(val)} to fit"


def test_the_climatology_reference_is_itself_leave_one_year_out():
    """Corrupt 1 year. Its own reference must not move; another year's must."""
    df = toy()
    years = sorted(df.year.unique())
    ref = T.climatology_reference(df, "y_t", years)

    bad = df.copy()
    hit = bad.year == years[3]
    bad.loc[hit, "y_t"] = 1.0
    ref2 = T.climatology_reference(bad, "y_t", years)

    np.testing.assert_allclose(
        ref[hit].to_numpy(), ref2[hit].to_numpy(), atol=1e-12,
        err_msg="the reference moved for the year that changed — it grades itself")
    other = bad.year == years[4]
    assert not np.allclose(ref[other].to_numpy(), ref2[other].to_numpy()), \
        "another year's reference should have moved and did not"


def test_calibration_is_fitted_out_of_fold():
    """An isotonic map fitted on the predictions it then scores flatters itself."""
    df = toy()
    years = sorted(df.year.unique())
    rng = np.random.default_rng(5)
    oof = pd.Series(np.clip(df.y_t * 0.3 + rng.uniform(0, 0.6, len(df)), 0, 1))

    cal = T.calibrate_oof(oof, df.y_t, df.year, years)
    hit = (df.year == years[2]).to_numpy()

    bumped = df.copy()
    bumped.loc[hit, "y_t"] = 1.0 - bumped.loc[hit, "y_t"]
    cal2 = T.calibrate_oof(oof, bumped.y_t, bumped.year, years)
    np.testing.assert_allclose(
        cal[hit].to_numpy(), cal2[hit].to_numpy(), atol=1e-12,
        err_msg="a year's calibrated values moved when only its own labels changed")


def test_shuffling_labels_destroys_the_skill():
    """The leakage control. If skill survives label shuffling, it came from the pipeline.

    Sized at 12,000 rows deliberately. At 1,500 the shuffled estimate has sd 0.0055 and
    the threshold sits inside its own noise; at 12,000 it is sd 0.0004 and the test has
    real power. The floor is ~0.0065 rather than 0 because the model can fit the
    unsmoothed per-cell rate that the +-7-day smoothed reference cannot — a reference
    artefact, not leakage, and the same reason the real control lands near +0.006.
    """
    df = toy(years=10, cells=12, days=100)
    years = sorted(df.year.unique())
    feats = ["f1", "f2"]
    ref = T.climatology_reference(df, "y_t", years).to_numpy()
    y = df.y_t.to_numpy(float)

    real, _ = T.loyo_predict(df, "y_t", feats, years, params={"n_estimators": 60})
    assert M.bss(y, real.to_numpy(), ref) > 0.02, "no signal to destroy — test is vacuous"

    y_s = T.shuffled_labels(df, "y_t", years, seed=0)
    # the reference must describe the shuffled world too — scoring against the REAL
    # labels' climatology compares two different worlds and hands the control free skill
    ref_s = T.climatology_reference(df.assign(y_t=y_s), "y_t", years).to_numpy()
    fake, _ = T.loyo_predict(df, "y_t", feats, years, shuffle_labels=True, seed=0,
                             params={"n_estimators": 60})
    assert M.bss(y_s, fake.to_numpy(), ref_s) < 0.01, "skill survived shuffling — leakage"


def test_calibration_improves_reliability_on_a_miscalibrated_forecast():
    rng = np.random.default_rng(6)
    df = toy()
    years = sorted(df.year.unique())
    skewed = pd.Series(np.clip(df.y_t * 0.25 + 0.5 + rng.normal(0, 0.05, len(df)), 0.01, 0.99))
    cal = T.calibrate_oof(skewed, df.y_t, df.year, years)
    y = df.y_t.to_numpy(float)
    assert M.murphy(y, cal.to_numpy())["reliability"] < M.murphy(y, skewed.to_numpy())["reliability"]


def test_the_saved_calibration_map_replays_without_scikit_learn():
    """P6 applies the isotonic map at inference. It must be reproducible from the two
    saved arrays by plain interpolation, or the shipped probabilities drift from the
    scored ones."""
    from sklearn.isotonic import IsotonicRegression

    rng = np.random.default_rng(7)
    p_raw = rng.uniform(0, 1, 3000)
    y = rng.binomial(1, p_raw).astype(float)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(p_raw, y)
    replay = np.interp(p_raw, iso.X_thresholds_, iso.y_thresholds_)
    np.testing.assert_allclose(iso.predict(p_raw), replay, atol=1e-12)


# --- the real trained artefacts --------------------------------------------

needs_run = pytest.mark.skipif(
    not METRICS.exists(), reason="run `.venv/bin/python scripts/train_model.py` first")


@pytest.fixture(scope="module")
def m():
    return json.loads(METRICS.read_text())


@needs_run
def test_every_target_was_trained_and_shipped(m):
    for t in T.TARGETS:
        assert t in m, f"{t} missing from metrics.json"
        assert (MODELS / f"{t}.txt").exists(), f"{t}: no booster saved"
        assert (MODELS / f"{t}_isotonic.npz").exists(), f"{t}: no calibration map saved"


@needs_run
def test_weeks_one_and_two_beat_climatology(m):
    """The whole phase in one assertion. BSS <= 0 means say so on the slide, not ship it."""
    for t in LEAD12:
        assert m[t]["bss"] > 0, f"{t}: BSS {m[t]['bss']:+.4f} — no skill over climatology"


@needs_run
def test_the_skill_interval_excludes_zero_where_we_claim_skill(m):
    """Mason 2004: BSS against climatology is negatively biased, so a point estimate alone
    is not evidence. The year-block interval is what makes the claim defensible."""
    for t in LEAD12:
        lo, _ = m[t]["bss_ci95"]
        assert lo > 0, f"{t}: 95% CI lower bound {lo:+.4f} touches zero"


@needs_run
def test_shuffling_the_labels_leaves_no_skill_on_the_real_data(m):
    c = m.get("_shuffle_control")
    assert c, "no shuffle control was run"
    assert abs(c["bss"]) < 0.01, f"control BSS {c['bss']:+.4f} — the pipeline leaks"


@needs_run
def test_the_reliability_curve_is_monotone_where_the_forecasts_actually_live(m):
    """If a higher forecast probability does not mean a higher observed frequency, the
    number on the farmer's screen does not mean what it says.

    Judged on bins holding at least 1% of predictions. A bin with 0.2% of rows cannot
    establish a calibration failure, and out-of-fold isotonic gives no monotonicity
    guarantee in the sparse tail — the map is fitted on 33 seasons and applied to a 34th.
    The tail is not waved away, it is bounded by the next test."""
    for t in LEAD12:
        total = m[t]["n"]
        pts = [r for r in m[t]["reliability_curve"] if r["n"] >= 0.01 * total]
        assert len(pts) >= 5, f"{t}: only {len(pts)} well-populated bins"
        obs = [r["observed"] for r in pts]
        drops = sum(1 for a, b in zip(obs, obs[1:]) if b < a - 0.02)
        assert drops == 0, f"{t}: reliability reverses {drops}x — {[round(o,3) for o in obs]}"


@needs_run
def test_the_sparse_tail_never_overstates_the_risk_badly(m):
    """The top bins DO overforecast: at 0.92 the event happens ~0.78 of the time. That is
    a real overstatement told to a farmer, so bound it and know how many it reaches."""
    for t in LEAD12:
        total = m[t]["n"]
        for r in m[t]["reliability_curve"]:
            over = r["p_mean"] - r["observed"]
            share = r["n"] / total
            assert over < 0.20, (
                f"{t}: forecasts {r['p_mean']:.2f}, happens {r['observed']:.3f} "
                f"— overstates by {over:.3f} on {share:.2%} of predictions")
            if over > 0.05:
                assert share < 0.01, (
                    f"{t}: {share:.2%} of predictions overstate risk by {over:.3f}")


@needs_run
def test_calibration_leaves_almost_no_reliability_error(m):
    for t in LEAD12:
        assert m[t]["reliability"] < 0.002, f"{t}: reliability {m[t]['reliability']:.5f}"


@needs_run
def test_the_model_discriminates_better_than_climatology_does(m):
    """Climatology already knows where and when. Skill has to come from the weather."""
    for t in LEAD12:
        assert m[t]["roc_auc"] > m[t]["roc_auc_climatology"], (
            f"{t}: AUC {m[t]['roc_auc']:.3f} vs climatology {m[t]['roc_auc_climatology']:.3f}")


@needs_run
def test_skill_is_not_carried_by_a_handful_of_seasons(m):
    """34 seasons is a small sample. If skill rests on 3 of them, say so rather than
    quote the aggregate."""
    for t in LEAD12:
        per_year = list(m[t]["by_year"].values())
        assert sum(1 for v in per_year if v > 0) >= 0.6 * len(per_year), (
            f"{t}: positive in only {sum(1 for v in per_year if v > 0)}/{len(per_year)} seasons")


@needs_run
def test_advisory_horizon_matches_where_skill_actually_is(m):
    """The app promises advice to 2 weeks and calls weeks 3-4 an outlook. That promise has
    to be the measurement, not a guess."""
    assert m["y_onset_7"]["bss"] > m["y_onset_28"]["bss"], "skill should decay with lead"


@needs_run
def test_oof_predictions_are_saved_for_the_skill_page(m):
    p = PROC / "oof_predictions.parquet"
    assert p.exists(), "P7 replay mode needs the out-of-fold predictions"
    df = pd.read_parquet(p)
    assert df["year"].nunique() == 34
    for t in LEAD12:
        assert t in df.columns and df[t].between(0, 1).all()


@needs_run
def test_the_app_publishes_measured_skill_not_invented_skill(m):
    """`/verify` exists to show honesty numbers. If those are still the hard-coded mock
    after P5 has run, the page is lying in the one place it must not."""
    latest = json.loads((ROOT / "forecast" / "latest.json").read_text())
    published = latest["skill"]
    assert "leave-one-year-out" in published["reference"], (
        "forecast still carries the pre-P5 skill block — rerun make_mock_forecast.py")
    assert published["bss"]["w1"] == pytest.approx(round(m["y_dry7_7"]["bss"], 4), abs=1e-6)
    assert published["roc_auc"] == pytest.approx(round(m["y_dry7_7"]["roc_auc"], 4), abs=1e-6)


@needs_run
def test_the_advisory_horizon_is_measured_rather_than_asserted(m):
    """The app advises to 2 weeks and calls the rest an outlook. That boundary has to be
    where BSS actually stops being positive."""
    latest = json.loads((ROOT / "forecast" / "latest.json").read_text())
    h = latest["skill"]["advisory_horizon_weeks"]
    leads = ["w1", "w2", "w3", "w4"]
    bss = latest["skill"]["bss"]
    for w in leads[:h]:
        assert bss[w] > 0, f"advising at {w} where BSS is {bss[w]:+.4f}"
    if h < 4:
        # the cut is on the INTERVAL, not the point estimate: y_dry7_28 scores +0.0155
        # with a 95% CI of (-0.010, 0.038), which is a number rather than skill
        metric_for = {"w1": "y_dry7_7", "w2": "y_dry7_14", "w3": "y_dry7_21", "w4": "y_dry7_28"}
        lo = m[metric_for[leads[h]]]["bss_ci95"][0]
        assert lo <= 0, f"horizon stops at {h} weeks but {leads[h]} CI lower bound is {lo:+.4f}"


@needs_run
def test_a_teammate_can_load_and_use_the_shipped_models():
    """Pushing models is pointless if nothing can read them back. This is the path a
    teammate takes after cloning: load, score, get calibrated probabilities."""
    from varshadrishti.model import predict as P

    assert len(P.available()) == len(T.TARGETS), f"shipped {P.available()}"
    df = pd.read_parquet(PROC / "features.parquet").head(500)
    out = P.predict_all(df)
    assert list(out.columns) == sorted(T.TARGETS)
    assert out.notna().all().all(), "inference produced NaN"
    assert ((out >= 0) & (out <= 1)).all().all(), "probability outside [0,1]"


@needs_run
def test_inference_matches_the_scored_predictions():
    """The shipped model is refit on all 34 seasons, so it cannot equal the out-of-fold
    numbers — but it must be close, or the thing measured is not the thing shipped."""
    from varshadrishti.model import predict as P

    df = pd.read_parquet(PROC / "features.parquet")
    oof = pd.read_parquet(PROC / "oof_predictions.parquet")
    sample = df.sample(5000, random_state=0)
    live = P.predict(sample, "y_dry7_7")
    scored = oof.loc[sample.index, "y_dry7_7"].to_numpy()
    assert np.corrcoef(live, scored)[0, 1] > 0.9, "shipped model disagrees with the scored one"


@needs_run
def test_inference_needs_no_scikit_learn_at_runtime():
    """The calibration ships as two arrays replayed with np.interp, so a deployment only
    needs lightgbm and numpy."""
    import ast

    src = (ROOT / "src" / "varshadrishti" / "model" / "predict.py").read_text()
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "sklearn" not in imported, f"inference imports {imported}"
    assert "np.interp" in src, "the calibration must be replayed by interpolation"
