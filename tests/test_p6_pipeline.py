"""P6 acceptance: the nightly job, offline, end to end.

The phase's own criterion is that real JSON replaces the mock and the frontend needs zero
changes. That is really a test of P1 — if the contract was frozen properly, swapping the
data source is invisible to the app. Most of what follows checks the ways a live pipeline
can look fine and be wrong: a partial cache, a one-sided blend, a probability of exactly
zero, climatology that drifts between training and serving.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti import contract as c  # noqa: E402
from varshadrishti.pipeline import aggregate as A  # noqa: E402
from varshadrishti.pipeline import blend as BL  # noqa: E402
from varshadrishti.pipeline import nwp as N  # noqa: E402
from varshadrishti.pipeline import observations as O  # noqa: E402

FORECAST = ROOT / "forecast"
PROC = ROOT / "data" / "processed"
CACHE = ROOT / "data" / "cache"
EVENTS = ("p_onset", "p_false_onset", "p_dry7", "p_dry14", "p_heavy")
LEADS = ("w1", "w2", "w3", "w4")

has_run = pytest.mark.skipif(
    not (CACHE / "ec46").glob("*.json") or not (CACHE / "obs").glob("*.json"),
    reason="no cached NWP/observations — run scripts/fetch_nwp.py and scripts/nightly.py")


# --- the ensemble estimator ------------------------------------------------


def test_zero_members_is_not_probability_zero():
    """0 of 81 members does not mean impossible; it means p below about 1/81. Publishing
    0.000 is a claim no proper score forgives."""
    assert N._member_fraction(0, 81) > 0
    assert N._member_fraction(81, 81) < 1
    assert N._member_fraction(0, 81) == pytest.approx(0.5 / 82)
    # and it must still be monotone and roughly right in the middle
    assert N._member_fraction(40, 81) == pytest.approx(40.5 / 82)
    fr = [N._member_fraction(k, 81) for k in range(82)]
    assert all(b > a for a, b in zip(fr, fr[1:]))


# --- the blend -------------------------------------------------------------


def test_the_blend_weights_say_which_leads_are_measured_and_which_are_not():
    """w1 is grounded in 118,218 verified pairs; w2-w4 are still a prior because no EC46
    hindcast exists at those leads. Whatever the wording, the string must distinguish the
    two — a weight that quietly stops declaring its provenance is the failure mode."""
    prov = BL.WEIGHT_PROVENANCE.lower()
    assert "measured" in prov, "no claim about what was verified"
    # GEFS is not EC46; that substitution must never stop being declared
    assert "proxy" in prov or "not ec46" in prov, "the proxy-model caveat is missing"
    assert set(BL.NWP_WEIGHT) == set(LEADS)
    w = [BL.NWP_WEIGHT[k] for k in LEADS]
    assert all(0 <= v <= 1 for v in w)
    # This used to assert monotone decay — a literature PRIOR the measurement does not
    # support. Fitted weights are 0.32 / 0.09 / 0.01 / 0.06 with fold sd 0.02/0.08/0.01/
    # 0.02, so w3 and w4 are both indistinguishable from zero and their order is noise.
    # What IS measured: week 1 carries most of the ensemble's value, and the long leads
    # carry almost none.
    assert w[0] > 0.15, "week 1 should still take meaningful ensemble weight"
    assert max(w[1:]) < 0.20, "long leads measured near zero; a large weight needs evidence"


def test_the_week_one_weight_respects_what_was_actually_measured():
    """The 2024 verification put the optimal DETERMINISTIC weight at 0.38 (1d) to 0.22
    (7d). The ensemble should beat a deterministic forecast, so the measurement is a
    floor — but the old 0.70 sat at roughly double it, which is what this pins."""
    m = ROOT / "logs" / "nwp_shortlead.json"
    if not m.exists():
        pytest.skip("run scripts/verify_nwp_shortlead.py")
    got = json.loads(m.read_text())
    floor = min(v["best_nwp_weight"] for v in got.values())
    ceil_ = max(v["best_nwp_weight"] for v in got.values())
    assert floor <= BL.NWP_WEIGHT["w1"] <= ceil_ + 0.15, (
        f"w1={BL.NWP_WEIGHT['w1']} is outside the measured range {floor}-{ceil_}")


def test_a_one_sided_blend_is_reported_not_hidden():
    idx = pd.Index(["c1", "c2"], name="cell_id")
    stat = pd.DataFrame({"p_dry7_w1": [0.4, 0.6], "p_heavy_w1": [np.nan, np.nan]}, index=idx)
    nwp = pd.DataFrame({"p_dry7_w1": [0.2, 0.2], "p_heavy_w1": [0.1, 0.3]}, index=idx)
    out, src = BL.blend(stat, nwp)
    assert src["p_dry7_w1"] == "blend"
    assert src["p_heavy_w1"] == "nwp_only"
    # the two-sided slot is pooled AND recalibrated, so it is not the raw weighted mean
    assert 0.0 < out.loc["c1", "p_dry7_w1"] < 1.0
    # a one-sided slot is a single source: no pool, therefore no transform
    assert out.loc["c1", "p_heavy_w1"] == pytest.approx(0.1), "absent side must not drag it down"


def test_recalibration_does_not_move_the_mean_forecast():
    """The transform must sharpen, not shift. A freely fitted Beta moved every dry-spell
    probability down ~0.07 because it was fitted at base rate 0.616 and applied at 0.40 —
    systematic under-warning, invisible in any reliability check of the source problem."""
    rng = np.random.default_rng(0)
    for shape in ((2, 3), (5, 2), (1.5, 1.5)):
        p = rng.beta(*shape, 4000)
        for w in (0.22, 0.45):
            q = BL.beta_transform(p, w)
            assert abs(q.mean() - p.mean()) < 1e-4, f"mean moved for Beta{shape} at w={w}"
            assert q.std() > p.std(), "a linear pool is under-sharp; the transform must sharpen"


def test_the_blend_never_leaves_the_unit_interval():
    idx = pd.Index(["c1"], name="cell_id")
    out, _ = BL.blend(pd.DataFrame({"p_dry7_w1": [1.0]}, index=idx),
                      pd.DataFrame({"p_dry7_w1": [1.0]}, index=idx))
    assert 0.0 <= out.loc["c1", "p_dry7_w1"] <= 1.0


# --- aggregation -----------------------------------------------------------


@pytest.mark.skipif(not (PROC / "weights_imd_hoblis.parquet").exists(), reason="run P2")
def test_area_weights_are_renormalised_over_the_cells_present():
    """One Karnataka cell is sea-masked in IMD. Without renormalising, the two hoblis that
    reference it have their probabilities silently scaled down by its weight."""
    w = A.load_weights("panchayat")
    cells = sorted(set(w.cell_id))[:-1]          # drop one, as the sea mask does
    probs = pd.DataFrame({"p_dry7_w1": np.full(len(cells), 0.5)},
                         index=pd.Index(cells, name="cell_id"))
    out = A.to_areas(probs, "panchayat")
    # every area is 0.5 everywhere, so the weighted mean must be 0.5 — not less
    assert out["p_dry7_w1"].min() == pytest.approx(0.5, abs=1e-9)
    assert out["p_dry7_w1"].max() == pytest.approx(0.5, abs=1e-9)


@pytest.mark.skipif(not (PROC / "weights_imd_hoblis.parquet").exists(), reason="run P2")
def test_aggregation_covers_every_area_at_every_level():
    w = A.load_weights("panchayat")
    cells = sorted(set(w.cell_id))
    probs = pd.DataFrame({"p_dry7_w1": np.linspace(0, 1, len(cells))},
                         index=pd.Index(cells, name="cell_id"))
    counts = {"district": 30, "block": 227, "panchayat": 870}
    for layer, n in counts.items():
        assert len(A.to_areas(probs, layer)) == n, f"{layer} lost areas"


# --- the observation cache -------------------------------------------------


def test_a_cache_written_for_fewer_cells_is_not_served_to_more(tmp_path, monkeypatch):
    """This bit for real: a 50-cell test fetch poisoned the cache, the nightly run read it
    and sent the other 274 cells down the NWP-only path with nothing in the logs."""
    monkeypatch.setattr(O, "CACHE", tmp_path)
    (tmp_path / "2026-01-01.json").write_text(json.dumps({
        "time": ["2026-01-01"], "cells": {"imd:1:1": [0.0]}}))
    calls = []
    monkeypatch.setattr(O, "_fetch", lambda cells, days: (calls.append(cells) or
                                                          {c: pd.Series([0.0], index=pd.to_datetime(["2026-01-01"]))
                                                           for c in cells}))
    O.fetch_recent(["imd:1:1", "imd:2:2"], "2026-01-01", log=lambda m: None)
    assert calls, "a short cache was served instead of refetching"


def test_a_complete_cache_is_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "CACHE", tmp_path)
    (tmp_path / "2026-01-01.json").write_text(json.dumps({
        "time": ["2026-01-01"], "cells": {"imd:1:1": [1.5]}}))
    monkeypatch.setattr(O, "_fetch", lambda *a: pytest.fail("refetched a complete cache"))
    df = O.fetch_recent(["imd:1:1"], "2026-01-01", log=lambda m: None)
    assert df.iloc[0, 0] == 1.5


# --- serving must not need the training archive ----------------------------


def test_inference_tables_exist_and_are_small_enough_to_commit():
    """A CI runner has the repo, not 825 MB of IMD .grd files."""
    p = PROC / "inference_tables.parquet"
    assert p.exists(), "run scripts/export_inference_tables.py"
    assert p.stat().st_size < 5_000_000, f"{p.stat().st_size / 1e6:.1f} MB is too big to commit"
    t = pd.read_parquet(p)
    for col in ("cell_id", "sday", "clim_rain_doy", "clim_dryday_doy", "onset_threshold_mm"):
        assert col in t.columns
    assert t.notna().all().all(), "NaN in the frozen inference table"


def test_the_nightly_job_does_not_import_the_imd_reader_at_serve_time():
    """`load_imd` in the serving path means the Action needs the archive to run."""
    src = (ROOT / "scripts" / "nightly.py").read_text()
    serve = src.split("if offline")[0]
    assert "load_imd" not in serve, "the live path reaches for the IMD archive"


def test_serving_climatology_matches_the_frozen_table():
    """Training used fold climatology, serving uses full-record. Different by design — but
    they must come from the same code, or live features drift from trained ones."""
    src = (ROOT / "src" / "varshadrishti" / "features" / "climatology.py").read_text()
    assert "def for_inference" in src and "_assemble" in src
    assert src.count("_assemble(") >= 3, "fold and inference paths must share the assembler"


# --- the end-to-end output -------------------------------------------------


@pytest.fixture(scope="module")
def latest():
    p = FORECAST / "latest.json"
    if not p.exists():
        pytest.skip("run scripts/nightly.py")
    return json.loads(p.read_text())


def test_the_output_validates_against_the_frozen_contract():
    p = FORECAST / "latest.json"
    if not p.exists():
        pytest.skip("run scripts/nightly.py")
    c.load_and_validate(p, "forecast.schema.json")


def test_latest_json_stays_inside_its_own_documented_budget():
    """P1 pinned <1.5 MB for latest.json at full scale — checked there only against a
    mock. The real file has no equivalent, and richer P8 advisories (up to 3 per area,
    every stage now genuinely reachable) grow it for real: 1.44 MB the day this was
    added, up from ~0.7 MB before the rules engine covered every stage. Caught here so
    the next rule added is weighed against the real budget, not just the mock's."""
    p = FORECAST / "latest.json"
    if not p.exists():
        pytest.skip("run scripts/nightly.py")
    mb = p.stat().st_size / 1_048_576
    assert mb < 1.5, f"{mb:.2f} MB — over the documented latest.json budget"


def test_every_published_probability_is_strictly_inside_the_unit_interval(latest):
    bad = []
    for aid, a in latest["areas"].items():
        for ev in EVENTS:
            for w, v in a[ev].items():
                if not 0.0 < v < 1.0:
                    bad.append(f"{aid}.{ev}.{w}={v}")
    assert not bad, f"{len(bad)} improper probabilities, e.g. {bad[:3]}"


def test_the_forecast_is_no_longer_marked_mock(latest):
    assert latest["meta"]["is_mock"] is False
    assert "mock" not in latest["meta"]["model_version"].lower()


def test_the_weight_caveat_travels_with_the_forecast(latest):
    """A reader of the JSON must be able to see which leads are verified and which are not,
    without reading the source."""
    prov = latest["provenance"]["nwp"]["weight_provenance"].lower()
    assert "measured" in prov
    assert "proxy" in prov or "not ec46" in prov


def test_the_excluded_features_are_recorded(latest):
    assert set(latest["provenance"]["statistical"]["excluded_features"]) == {
        "oni", "dmi", "nino34_anom"}


def test_every_area_still_carries_a_cited_advisory(latest):
    missing = [k for k, a in latest["areas"].items() if not a.get("advisories")]
    assert not missing, f"{len(missing)} areas lost their advisory"
    for a in latest["areas"].values():
        for adv in a["advisories"]:
            assert "CRIDA" in adv["source"]["doc"]


def test_confidence_reflects_that_skill_is_month_dependent(latest):
    """P5b: dry-spell BSS is +0.076 in July and +0.020 in September. A September card must
    not be presented with July's authority."""
    month = int(latest["meta"]["valid_from"][5:7])
    levels = {a["confidence"] for a in latest["areas"].values()}
    assert levels <= {"low", "medium", "high"}
    if month not in (7, 8):
        assert "high" not in levels, f"month {month} is not a high-skill month"


def test_no_advisory_claims_a_seasonal_outlook(latest):
    """The model has no seasonal-anomaly skill — per-season bias 0.055 against
    climatology's 0.064. It can say a break is coming; it can never say it will be a
    drought year."""
    banned = ("this season", "drought year", "seasonal outlook", "whole season",
              "entire season", "rest of the season")
    hits = []
    for a in latest["areas"].values():
        for adv in a["advisories"]:
            text = f"{adv.get('action_en','')} {adv.get('reason_en','')}".lower()
            hits += [f"{adv['rule_id']}: {b}" for b in banned if b in text]
    assert not hits, f"seasonal-outlook language: {sorted(set(hits))[:3]}"


# --- the P1 checkpoint -----------------------------------------------------


def test_the_frontend_needs_no_change_to_read_the_live_forecast(latest):
    """The real P6 checkpoint, and the test that P1 was worth doing: every field the app
    reads must be present with the same shape it had under the mock."""
    api = (ROOT / "web" / "src" / "lib" / "api.js").read_text()
    assert "p_dry7" in api and "advisory_horizon_weeks" in api

    a = next(iter(latest["areas"].values()))
    for ev in EVENTS:
        assert set(a[ev]) == set(LEADS), f"{ev} lost a lead"
    for field in ("area_id", "name_en", "level", "onset_status", "confidence"):
        assert field in a
    assert set(latest["skill"]["bss"]) == set(LEADS)
    assert "advisory_horizon_weeks" in latest["skill"]


def test_the_per_area_files_the_app_fetches_all_exist(latest):
    n = len(list((FORECAST / "area").glob("*.json")))
    assert n == len(latest["areas"]), f"{n} area files for {len(latest['areas'])} areas"
    sizes = [p.stat().st_size for p in (FORECAST / "area").glob("*.json")]
    assert max(sizes) <= c.AREA_FILE_MAX_BYTES, "an area file blew the 2G budget"


# --- the scheduled job -----------------------------------------------------


def test_the_workflow_installs_only_what_serving_needs():
    wf = (ROOT / ".github" / "workflows" / "nightly.yml").read_text()
    assert "requirements.txt" not in wf, "the runner does not need geopandas or imdlib"
    assert "xgboost" in wf and "pyarrow" in wf
    assert "scripts/nightly.py" in wf
    assert "test_p6_pipeline.py" in wf, "the job must verify its own output before committing"
    assert "concurrency" in wf, "two overlapping runs would fight over the commit"


def test_the_workflow_tolerates_a_failed_nwp_fetch():
    """A stale cached run still produces a forecast; an outage must not mean no forecast."""
    wf = (ROOT / ".github" / "workflows" / "nightly.yml").read_text()
    block = wf.split("Fetch NWP")[1].split("- name:")[0]
    assert "continue-on-error: true" in block


def test_the_provenance_sentence_has_exactly_one_source():
    """It was built independently in three places and they drifted. Since `npm run build`
    runs split_forecast, a web build silently rewrote live area files with the mock's
    wording — visible only as a byte diff in an unrelated P2 test."""
    import inspect

    assert hasattr(c, "provenance_summary")
    for script in ("nightly.py", "split_forecast.py", "make_mock_forecast.py"):
        src = (ROOT / "scripts" / script).read_text()
        assert "provenance_summary(" in src, f"{script} does not call the shared builder"
        assert "years of IMD rainfall for your hobli" not in src, (
            f"{script} still hardcodes the sentence")
    assert "Based on" in inspect.getsource(c.provenance_summary)


def test_everything_the_action_needs_is_actually_committed():
    """The Action installs no geopandas and downloads no IMD archive, so every input it
    cannot fetch must be in the repo. `inference_tables.parquet` was gitignored by
    `data/processed/*.parquet` — the file created specifically to make CI work would have
    been absent from CI."""
    needed = [
        PROC / "inference_tables.parquet",
        PROC / "weights_imd_hoblis.parquet",
        PROC / "weights_imd_blocks.parquet",
        PROC / "weights_imd_districts.parquet",
        ROOT / "rules" / "default.yaml",
    ]
    needed += sorted(ROOT.glob("models/y_*.txt"))[:1]
    for f in needed:
        assert f.exists(), f"{f} missing"
        r = subprocess.run(["git", "check-ignore", str(f)], cwd=ROOT,
                           capture_output=True, text=True)
        assert r.returncode != 0, f"{f.relative_to(ROOT)} is gitignored — CI will not have it"


def test_the_pipeline_covers_every_slot_the_contract_publishes():
    """`p_false_onset` — the headline label of the whole project — had no model at all and
    was being published from the ensemble alone."""
    from varshadrishti.pipeline import infer as I  # noqa: PLC0415

    assert I.missing_models() == [], f"no model behind {I.missing_models()}"


def test_slots_with_no_measured_skill_are_named_in_the_payload(latest):
    """`y_dry14_28` scores -0.0003 with an interval spanning zero. The contract needs four
    leads per event so it is still published — but a reader must be able to tell it apart
    from `y_onset_7` at +0.31, and no UI should be able to present the two alike."""
    import json as _json

    metrics = _json.loads((ROOT / "models" / "metrics.json").read_text())
    fam = {"p_onset": "y_onset", "p_false_onset": "y_false_onset", "p_dry7": "y_dry7",
           "p_dry14": "y_dry14", "p_heavy": "y_heavy"}
    expected = {f"{ev}_{w}" for ev, f in fam.items()
                for w, h in (("w1", 7), ("w2", 14), ("w3", 21), ("w4", 28))
                if metrics.get(f"{f}_{h}", {}).get("bss_ci95", [1.0])[0] <= 0}
    published = set(latest["skill"].get("no_skill_slots", []))
    assert published == expected, f"published {published}, measured {expected}"
    # and the slot is still present in every area — omitting it would break the contract
    a = next(iter(latest["areas"].values()))
    for slot in published:
        ev, w = slot.rsplit("_", 1)
        assert w in a[ev], f"{slot} was dropped instead of flagged"


def test_a_flagged_slot_is_still_a_real_probability(latest):
    for slot in latest["skill"].get("no_skill_slots", []):
        ev, w = slot.rsplit("_", 1)
        vals = [a[ev][w] for a in latest["areas"].values()]
        assert all(0.0 < v < 1.0 for v in vals), f"{slot} carries improper values"


# --- PS 26086: global boundary conditions -----------------------------------


def test_all_three_named_indices_are_ingested():
    """The PS names ENSO, IOD and MJO. All three must be ingested — what differs is where
    each is ALLOWED to act, which is decided by measurement, not by the PS wording."""
    from varshadrishti.features.indices import load_indices  # noqa: PLC0415

    idx = load_indices()
    for col in ("oni", "dmi", "nino34_anom", "rmm1", "rmm2", "mjo_amp", "mjo_phase"):
        assert col in idx.columns, f"{col} not ingested"
        assert idx[col].notna().sum() > 1000, f"{col} is empty"


def test_mjo_is_in_the_model_and_enso_iod_are_not():
    """Measured: MJO +0.018 to +0.019 BSS; ENSO/IOD harmful at every lead, paired
    P(worse) up to 1.000. Each index acts at the timescale where it works."""
    from varshadrishti.model import train as T  # noqa: PLC0415

    df = pd.read_parquet(PROC / "features.parquet")
    feats = T.feature_names(df)
    assert "rmm1" in feats and "mjo_amp" in feats, "MJO must be in the model"
    assert not ({"oni", "dmi", "nino34_anom"} & set(feats)), "ENSO/IOD must not be"


def test_enso_context_is_published_and_marked_as_not_a_forecast(latest):
    """PS 26086 asks for global boundary conditions. ENSO is reported as CONTEXT because
    it tracks the season total (r = -0.39) but cannot improve 1-4 week timing. The
    payload must say so — we have no seasonal-anomaly skill to claim."""
    t = latest["provenance"].get("teleconnection")
    assert t, "no teleconnection block — the PS asks for these indices"
    assert t["is_forecast"] is False, "ENSO context must never be flagged as a forecast"
    assert t["enso_phase"] in ("el_nino", "la_nina", "neutral")
    assert -10 < t["oni"] < 10, f"ONI {t['oni']} is a sentinel, not a measurement"
    for banned in ("will be", "expect", "forecast for this season", "predicted"):
        assert banned not in t["basis"].lower(), f"context reads as a prediction: {banned}"


def test_el_nino_seasons_are_flagged_as_lower_reliability(latest):
    """corr(model skill, ONI) = -0.32; the four worst seasons were El Nino or +IOD. An
    officer must not read a strong-El-Nino forecast with normal-season confidence."""
    t = latest["provenance"]["teleconnection"]
    expected = "reduced" if t["enso_phase"] == "el_nino" else "typical"
    assert t["model_reliability"] == expected


def test_a_publication_lag_is_not_read_as_a_missing_index():
    """ONI is monthly and published in arrears, so the newest valid value is often weeks
    old. Taking the last ROW instead of the last VALID one reads as 'no ENSO data'."""
    from varshadrishti.pipeline import teleconnection as TC  # noqa: PLC0415

    got = TC.current("2026-09-19")
    assert got, "a normal publication lag was read as missing data"


def test_sentinel_index_values_never_reach_the_features():
    """NOAA marks an unpublished ONI month -99.9 — in nobody's documented sentinel list,
    and it reads as a record La Nina. It reached the live ENSO classifier once."""
    from varshadrishti.features.indices import load_indices  # noqa: PLC0415

    idx = load_indices()
    for col in ("oni", "dmi", "nino34_anom"):
        v = idx[col].dropna()
        assert v.abs().max() < 99, f"{col} still carries a sentinel ({v.abs().max()})"
    # and the absolute-SST series must survive the magnitude mask that anomalies need
    assert load_indices()["nino34"].notna().sum() > 10000, "nino34 was masked away"


# --- W1: the blend must be recalibrated after pooling ----------------------


def test_recalibration_is_applied_only_where_it_was_measured_to_help():
    """W1, settled on real blend outcomes rather than a proxy.

    Leave-one-season-out over 6 seasons and 20,274 triples: w1 improves (Brier 0.17564 ->
    0.17410, CI +0.00016 to +0.00290, P(worse) 0.017) and w2-w4 do not move at all. That
    is the theorem behaving correctly, not a null result — at weights of 0.09/0.01/0.06
    the "pool" is essentially P_stat alone and is already calibrated, so there is nothing
    to fix. Applying it there anyway is how an earlier attempt made things worse."""
    assert set(BL.RECALIBRATE) == {"w1"}, (
        f"recalibration is enabled at {sorted(BL.RECALIBRATE)}; only w1 was validated")
    assert BL.RECALIBRATE["w1"] > 2.0, "strength 2.0 is the identity — that is not applying it"


def test_recalibration_sharpens_without_moving_the_mean():
    """A freely fitted Beta also shifts location. Ours was fitted at base rate 0.616 and
    applied at 0.40, pushing every dry-spell probability down ~0.07 — systematic
    under-warning, invisible in the source problem's own reliability check."""
    rng = np.random.default_rng(0)
    for shape in ((2, 3), (5, 2), (1.5, 1.5)):
        q = rng.beta(*shape, 4000)
        out = BL.mean_preserving(q, BL.RECALIBRATE["w1"])
        assert abs(out.mean() - q.mean()) < 1e-3, f"mean moved for Beta{shape}"
        assert out.std() > q.std(), "a linear pool is under-sharp; this must sharpen"


def test_the_validated_gain_is_recorded(latest):
    """If someone changes the weights, the recalibration must be re-validated — the two
    are coupled, because how much the pool needs correcting depends on how much pooling
    there is."""
    m = ROOT / "logs" / "w1_recalibration.json"
    if not m.exists():
        pytest.skip("run scripts/validate_w1_recalibration.py")
    got = json.loads(m.read_text())
    assert got["w1"]["ci95"][0] > 0, "w1 recalibration no longer clears zero — re-derive"
    for lead in ("w2", "w3", "w4"):
        assert lead not in BL.RECALIBRATE, f"{lead} measured no gain but is enabled"


def test_published_windowed_risk_does_not_rise_monotonically_with_lead():
    """P_nwp is windowed ("in week k") and P_stat was cumulative ("within k weeks"), so
    the blend averaged two different events. It showed: published p_dry7 climbed 0.351 ->
    0.772 across the ribbon, which reads as "risk grows every week" and was cumulation.
    The cumulative targets are nested, so the windowed value is their exact difference."""
    p = FORECAST / "latest.json"
    if not p.exists():
        pytest.skip("run scripts/nightly.py")
    latest = json.loads(p.read_text())
    means = [float(np.mean([a["p_dry7"][w] for a in latest["areas"].values()]))
             for w in LEADS]
    assert means[0] > means[-1], f"windowed risk should not grow with lead: {means}"
    # strict monotonicity is not required — w2 and w3 sit within noise of each other —
    # but the cumulation artefact (0.351 -> 0.772) must not return
    assert means[0] > means[1] and means[2] > means[3], f"cumulation artefact back: {means}"


def test_the_beta_transform_is_the_identity_when_there_is_no_nwp():
    """With w=0 the pool IS the calibrated statistical forecast. Transforming it would
    corrupt a probability that was already right."""
    p = np.array([0.01, 0.3, 0.5, 0.95])
    np.testing.assert_allclose(BL.beta_transform(p, 0.0), p)


def test_the_transform_strengthens_with_the_nwp_weight():
    """More uncalibrated input means more correction needed."""
    rng = np.random.default_rng(1)
    p = rng.beta(2, 3, 4000)
    sds = [BL.beta_transform(p, w).std() for w in (0.1, 0.22, 0.35, 0.45)]
    assert all(b > a for a, b in zip(sds, sds[1:])), "more NWP should mean more sharpening"
    assert BL.sharpen_strength(0.45) > BL.sharpen_strength(0.22)


def test_the_transform_preserves_the_unit_interval_and_monotonicity():
    p = np.linspace(0.001, 0.999, 200)
    q = BL.beta_transform(p, 0.45)
    assert (q >= 0).all() and (q <= 1).all()
    assert (np.diff(q) >= -1e-12).all(), "a recalibration that reorders forecasts is wrong"


def test_the_calibration_method_is_named_in_the_payload(latest):
    """The XGBoost boosters ship no isotonic map, so the payload must say so rather than
    inherit the retired backend's claim. The linear pool is still uncalibrated."""
    cal = latest["provenance"]["calibration"].lower()
    assert "none on the statistical model" in cal, "the absence of calibration is not declared"
    assert "beta" in cal, "the pool's recalibration status is not declared"





def test_the_weights_are_the_ones_that_were_measured():
    """W2: 20,274 first-occurrence triples, 6 seasons, GEFSv12 vs IMD, fitted
    leave-one-season-out. Every earlier value here was wrong — a literature prior said
    0.80 at w1, an extrapolation said 0.45, and a run comparing mismatched events said
    1.00. If these drift, they must drift because something was re-measured."""
    assert BL.NWP_WEIGHT == {"w1": 0.32, "w2": 0.09, "w3": 0.01, "w4": 0.06}


def test_the_statistical_model_outranks_the_ensemble_at_every_lead():
    """The measurement's headline, and the reason the weights are low: P_stat beats the
    GEFS ensemble at all four leads, by more as lead grows."""
    m = ROOT / "logs" / "blend_weights_measured.json"
    if not m.exists():
        pytest.skip("run scripts/derive_blend_weights.py")
    got = json.loads(m.read_text())
    for lead, d in got.items():
        assert d["brier_stat_only"] < d["brier_nwp_only"], (
            f"{lead}: ensemble {d['brier_nwp_only']:.4f} beat the model "
            f"{d['brier_stat_only']:.4f} — the weights need re-deriving")
        assert d["weight_loyo_sd"] < 0.15, f"{lead}: fold spread {d['weight_loyo_sd']}"
