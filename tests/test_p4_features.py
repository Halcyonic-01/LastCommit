"""P4 acceptance: labels, causal features, leave-one-year-out climatology.

The two tests that matter here perturb the data and check what moves. A feature that
reads the future, or a climatology that has seen its own year, both survive any amount
of source-reading and are caught immediately by poking the inputs.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti.features import build as B  # noqa: E402
from varshadrishti.features import labels as L  # noqa: E402
from varshadrishti.features.indices import load_indices, load_mjo  # noqa: E402

PROC = ROOT / "data" / "processed"
FEATURES = PROC / "features.parquet"
ONSET = PROC / "onset_labels.parquet"

SEASONS = list(range(1991, 2025))

# A 40 mm burst over 5 days. A 35 mm bar is cleared only by the window holding all five
# days — at 25 mm the window starting a day earlier also clears it on 32 mm of the same
# rain, which is correct behaviour but makes the expected index ambiguous in a test.
BURST_BAR = 35.0


def synth(years, cells=4, seed=0):
    """A small synthetic monsoon: a wet season with a mid-season break in some cells."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{min(years)}-01-01", f"{max(years)}-12-31", freq="D")
    cols = [f"imd:{10 + i}:{75 + i}" for i in range(cells)]
    x = np.zeros((len(idx), cells))
    season = (idx.month >= 6) & (idx.month <= 9)
    x[season] = rng.gamma(1.2, 6.0, size=(season.sum(), cells))
    return pd.DataFrame(x, index=idx, columns=cols)


# --- the onset definition --------------------------------------------------


def test_a_burst_followed_by_drought_is_a_false_start_not_an_onset():
    x = np.zeros(150)
    x[10:15] = 8.0  # 40 mm over 5 days, 5 rainy days — clears any local bar
    onset, false_starts = L.onset_for_cell(x, BURST_BAR)
    assert onset is None
    assert false_starts == [10]


def test_a_burst_followed_by_steady_rain_is_a_confirmed_onset():
    x = np.zeros(150)
    x[10:15] = 8.0
    x[15:70] = 4.0
    onset, false_starts = L.onset_for_cell(x, BURST_BAR)
    assert onset == 10 and false_starts == []


def test_one_burst_counts_once_not_five_times():
    """5 overlapping windows describe the same rain. Counting windows inflates the rate."""
    x = np.zeros(150)
    x[10:15] = 8.0
    _, false_starts = L.onset_for_cell(x, BURST_BAR)
    assert len(false_starts) == 1, f"one burst produced {len(false_starts)} false starts"


def test_a_false_start_does_not_hide_the_real_onset_behind_it():
    x = np.zeros(150)
    x[10:15] = 8.0          # fails
    x[45:50] = 8.0          # succeeds
    x[50:110] = 4.0
    onset, false_starts = L.onset_for_cell(x, BURST_BAR)
    assert onset == 45 and false_starts == [10]


def test_drizzle_never_counts_as_a_sowing_rain():
    """25 mm spread as 5 x 5 mm clears a 25 mm bar but only if the days are rainy days."""
    x = np.zeros(150)
    x[10:15] = 2.0  # 10 mm total, no rainy day
    onset, false_starts = L.onset_for_cell(x, 25.0)
    assert onset is None and false_starts == []


# --- the local threshold ---------------------------------------------------


def test_the_onset_bar_stays_inside_an_agronomic_band():
    """The local mean 5-day wet spell is ~390 mm in the Ghats. Germination is not."""
    rain = synth(range(1991, 1996))
    t = L.wet_spell_threshold(rain, range(1991, 1996))
    assert (t >= L.ONSET_FLOOR_MM).all(), "a cell may not onset on less than the floor"
    assert (t <= L.ONSET_CAP_MM).all(), "a cell may not need a cloudburst to onset"


def test_a_wetter_cell_gets_a_higher_bar_than_a_drier_one():
    rain = synth(range(1991, 1996))
    rain.iloc[:, 0] *= 4.0  # make cell 0 much wetter
    t = L.wet_spell_threshold(rain, range(1991, 1996))
    assert t.iloc[0] >= t.iloc[1]


# --- causality: nothing may read the future --------------------------------


def test_no_feature_reads_a_single_day_into_the_future():
    """Rewrite the season after day 60 and assert every feature up to day 60 is identical."""
    rain = synth([2000])
    season = L._season_slice(rain, 2000)
    thresh = L.wet_spell_threshold(rain, [2000])

    before = B.causal_features(season, thresh)
    tampered = season.copy()
    tampered.iloc[61:] = 999.0  # a future no model should be able to see
    after = B.causal_features(tampered, thresh)

    for name in before:
        a = before[name].iloc[:61]
        b = after[name].iloc[:61]
        pd.testing.assert_frame_equal(a, b, obj=f"feature {name} reads the future")


def test_the_confirmed_onset_date_is_not_a_feature():
    """Confirming an onset needs 30 days of hindsight, so it cannot be known on the day."""
    rain = synth([2000])
    season = L._season_slice(rain, 2000)
    f = B.causal_features(season, L.wet_spell_threshold(rain, [2000]))
    assert "onset_happened" not in f
    assert "wet_spell_seen" in f, "the knowable CANDIDATE should be there instead"


def test_targets_do_look_ahead_because_that_is_what_they_are():
    """The mirror of the test above: if a target did not move, it is not a target."""
    rain = synth([2000])
    season = L._season_slice(rain, 2000)
    thresh = L.wet_spell_threshold(rain, [2000])
    before = B.targets(rain, season.index, thresh)
    tampered = rain.copy()
    tampered.loc["2000-08-01":] = 0.0
    after = B.targets(tampered, season.index, thresh)
    assert not before["y_dry7_7"].iloc[:61].equals(after["y_dry7_7"].iloc[:61]) or \
           not before["y_dry7_7"].equals(after["y_dry7_7"]), "targets must see ahead"


# --- leave-one-year-out climatology ----------------------------------------


def test_climatology_for_a_year_never_uses_that_year():
    """Corrupt 1993 alone. Its own climatology must not move; the others must."""
    years = list(range(1991, 1997))
    rain = synth(years)
    thresh = L.wet_spell_threshold(rain, years)
    onset = pd.concat([L.season_labels(rain, y, thresh) for y in years], ignore_index=True)
    clim = B.loyo_climatology(rain, years, onset)

    bad = rain.copy()
    bad.loc["1993-06-01":"1993-09-30"] = 500.0
    onset2 = pd.concat([L.season_labels(bad, y, thresh) for y in years], ignore_index=True)
    clim2 = B.loyo_climatology(bad, years, onset2)

    pd.testing.assert_frame_equal(
        clim[1993]["clim_rain_doy"], clim2[1993]["clim_rain_doy"],
        obj="1993's climatology moved when only 1993 changed — it is fitted on itself")
    assert not clim[1994]["clim_rain_doy"].equals(clim2[1994]["clim_rain_doy"]), \
        "1994's climatology should include 1993 and therefore should have moved"


# --- the climate indices ---------------------------------------------------


def test_monthly_indices_are_lagged_to_publication():
    """ONI for month M is a 3-month mean centred on M — unknowable inside M."""
    idx = load_indices()
    jan = idx.loc["1998-01-15", "oni"]
    dec = idx.loc["1997-12-15", "oni"]
    assert not np.isclose(jan, dec), "the lag collapsed; a month's value is arriving too early"
    assert B.INDEX_COLS, "no index columns configured"


def test_mjo_covers_every_training_season():
    """The old BoM path still serves 200 OK frozen at 2024-02-24 — silent staleness."""
    mjo = load_mjo()
    last = mjo["rmm1"].last_valid_index()
    assert last >= pd.Timestamp(2024, 9, 30), (
        f"MJO ends {last.date()}; the 2024 monsoon has no MJO. Re-run download_indices.py")


def test_mjo_phase_is_dropped_when_there_is_no_coherent_wave():
    mjo = load_mjo()
    weak = mjo[mjo["mjo_amp"] < 1.0]
    assert weak["mjo_phase"].isna().all(), "phase is noise below amplitude 1"


# --- the built table -------------------------------------------------------

needs_build = pytest.mark.skipif(
    not FEATURES.exists(), reason="run scripts/build_features.py first")


@pytest.fixture(scope="module")
def built():
    return pd.read_parquet(FEATURES)


@pytest.fixture(scope="module")
def onsets():
    return pd.read_parquet(ONSET)


@needs_build
def test_every_season_is_present_and_the_same_size(built):
    n = built.groupby("year").size()
    assert list(n.index) == SEASONS, f"missing seasons: {set(SEASONS) - set(n.index)}"
    assert n.nunique() == 1, f"seasons differ in size: {n.to_dict()}"


@needs_build
def test_no_missing_value_flag_leaks_into_any_column(built):
    """-999 is IMD's sea flag. Masked with `< 1000` it survives into every rolling sum."""
    num = built.select_dtypes("number")
    hits = {c: float(num[c].min()) for c in num if num[c].min() <= -999}
    assert not hits, f"sentinel leaked into {hits}"


@needs_build
def test_onset_dates_fall_in_the_monsoon_not_at_its_edges(onsets):
    m = onsets["onset_date"].dropna().dt.month
    assert m.between(6, 8).all(), f"onsets outside Jun-Aug: {sorted(m.unique())}"


def _banded(onsets, built):
    """Join each cell-season to how wet that cell is, so results can be read by regime."""
    wet = built.groupby("cell_id")["clim_rain_doy"].mean() * 122  # season-total proxy, mm
    o = onsets.copy()
    o["season_mm"] = o["cell_id"].map(wet)
    o["band"] = pd.cut(o["season_mm"], [0, 400, 600, 800, 1200, 1e9],
                       labels=["<400", "400-600", "600-800", "800-1200", ">1200"])
    return o


@needs_build
def test_false_onset_rate_is_in_the_published_range_where_the_method_applies(onsets, built):
    """Moron-Robertson report 10-40%. That is what we get in normal-rainfall cells. The
    rain shadow runs far higher, which is the finding rather than a defect, so the
    published range is asserted on the regime the published method was calibrated on."""
    o = _banded(onsets, built)
    for band in ("600-800", "800-1200"):
        rate = o[o.band == band]["first_cand_failed"].mean()
        assert 0.10 <= rate <= 0.40, f"{band} mm cells fail at {rate:.1%}, outside 10-40%"


@needs_build
def test_failure_risk_rises_monotonically_as_a_cell_gets_drier(onsets, built):
    """The product's whole thesis in one assertion. A label set that does not reproduce
    this gradient is measuring noise, whatever its aggregate rate looks like."""
    o = _banded(onsets, built)
    rates = o.groupby("band", observed=True)["first_cand_failed"].mean()
    ordered = rates.reindex(["<400", "400-600", "600-800", "800-1200", ">1200"]).dropna()
    assert list(ordered) == sorted(ordered, reverse=True), (
        f"failure rate is not monotone in dryness:\n{ordered.round(3)}")
    assert ordered.iloc[0] - ordered.iloc[-1] > 0.30, "dry belt and Ghats barely differ"


@needs_build
def test_seasons_with_no_sowing_rain_at_all_are_droughts_not_noise(onsets, built):
    """~5% of cell-seasons never see a 5-day 20 mm spell. If that were scattered evenly it
    would be a threshold bug; concentrated in the driest cells and worst years, it is the
    signal the product exists to give."""
    o = _banded(onsets, built)
    none = o[o["first_cand_doy"].isna()]
    assert 0.02 <= len(none) / len(o) <= 0.10, f"{len(none)/len(o):.1%} of cell-seasons"
    assert none["season_mm"].median() < o["season_mm"].median(), "not concentrated in dry cells"
    worst = none["year"].value_counts()
    assert worst.head(5).sum() / len(none) > 0.30, "spread evenly across years — looks like a bug"


@needs_build
def test_no_target_is_degenerate(built):
    for c in [c for c in built.columns if c.startswith("y_")]:
        rate = built[c].mean()
        assert 0.01 < rate < 0.99, f"{c} base rate {rate:.3f} — nothing to learn"


@needs_build
def test_base_rates_are_left_alone(built):
    """Resampling to balance classes is what destroys calibration, and Brier is the metric.
    The table must ship at its natural base rate so P5 can weight instead."""
    assert built["y_heavy_7"].mean() < 0.25, "heavy rain is rare; a balanced table is wrong"


@needs_build
def test_every_row_carries_the_year_so_p5_can_split_on_it(built):
    """Random splits leak: neighbouring cells in one season are the same weather event."""
    assert "year" in built.columns
    assert built["year"].nunique() == len(SEASONS)


@needs_build
def test_no_feature_hands_a_target_its_own_answer(built):
    """The bug this catches, found the hard way: `y_onset_7` once included day t, and
    `wet_spell_today` is a feature, so P(target | feature) was exactly 1.000. The model
    scored BSS +0.43 by reading the answer off its input. Any feature that determines a
    target outright is either a definitional overlap or leakage — both are fatal."""
    targets = [c for c in built.columns if c.startswith("y_")]
    feats = [c for c in built.columns
             if c not in targets and c not in ("date", "cell_id", "year", "sday")]
    offenders = []
    for f in feats:
        col = built[f]
        # only features that act like a flag can be tautological on their own
        vals = col.dropna().unique()
        if len(vals) != 2:
            continue
        on = col == max(vals)
        if on.sum() < 1000:
            continue
        for t in targets:
            rate = built.loc[on, t].mean()
            if rate > 0.999 or rate < 0.001:
                offenders.append(f"{f}=1 -> P({t})={rate:.4f}")
    assert not offenders, "a feature determines a target outright:\n" + "\n".join(offenders)


@needs_build
def test_every_target_asks_about_the_future_not_today(built):
    """"In the next 7 days" must mean t+1..t+7. Including today makes the forecast a
    statement about weather the farmer can already see out of the window."""
    src = (ROOT / "src" / "varshadrishti" / "features" / "labels.py").read_text()
    assert "shift(-1)" in src, "within_horizon must drop the current day from the horizon"
