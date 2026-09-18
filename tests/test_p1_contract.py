"""P1 acceptance: the forecast contract holds, and rejects what it should."""

import json
import subprocess
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti import contract as c  # noqa: E402

@pytest.fixture(scope="module")
def forecast_dir(tmp_path_factory):
    """Fixture areas in a temp dir — never touches the real forecast/ that P2 populates."""
    out = tmp_path_factory.mktemp("forecast")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_mock_forecast.py"),
         "--valid-from", "2026-09-19", "--fixture", "--out", str(out)],
        check=True, capture_output=True,
    )
    return out


@pytest.fixture(scope="module")
def generated(forecast_dir):
    return json.loads((forecast_dir / "latest.json").read_text())


# --- the emitted files validate ------------------------------------------


def test_latest_validates(generated):
    c.validate(generated, "forecast.schema.json")


def test_index_validates(forecast_dir):
    c.load_and_validate(forecast_dir / "index.json", "index.schema.json")


def test_every_area_file_validates(forecast_dir):
    files = list((forecast_dir / "area").glob("*.json"))
    assert files, "no area files emitted"
    for f in files:
        c.load_and_validate(f, "area.schema.json")


def test_archive_copy_written(generated, forecast_dir):
    stamp = generated["meta"]["valid_from"]
    c.load_and_validate(forecast_dir / "archive" / f"{stamp}.json", "forecast.schema.json")


# --- invariants the app depends on ---------------------------------------


def test_all_probabilities_in_unit_interval(generated):
    heads = ["p_onset", "p_false_onset", "p_dry7", "p_dry14", "p_heavy"]
    for aid, a in generated["areas"].items():
        for head in heads:
            for lead, v in a[head].items():
                assert 0.0 <= v <= 1.0, f"{aid}.{head}.{lead} = {v}"


def test_farmer_payload_within_2g_budget(forecast_dir):
    for f in (forecast_dir / "area").glob("*.json"):
        size = f.stat().st_size
        assert size <= c.AREA_FILE_MAX_BYTES, f"{f.name} is {size} B"


def test_area_file_matches_latest_for_same_area(generated, forecast_dir):
    """The two paths must never disagree — officer and farmer see the same numbers."""
    for f in (forecast_dir / "area").glob("*.json"):
        body = json.loads(f.read_text())["forecast"]
        assert body == generated["areas"][body["area_id"]]


def test_index_covers_every_area(generated, forecast_dir):
    idx = json.loads((forecast_dir / "index.json").read_text())["areas"]
    assert set(idx) == set(generated["areas"]), "index and latest.json disagree on areas"


def test_geometry_is_not_in_forecast_files(generated):
    """Polygons live in geo/*.geojson and are fetched once — never shipped daily."""
    blob = json.dumps(generated)
    for banned in ('"geometry"', '"coordinates"', '"Feature"', '"Polygon"'):
        assert banned not in blob, f"{banned} leaked into the daily payload"


def test_every_advisory_cites_a_source(generated):
    found = 0
    for a in generated["areas"].values():
        for adv in a.get("advisories", []):
            assert adv["source"]["doc"] and adv["source"]["table"]
            assert adv["action_en"] and adv["action_kn"], "both languages required"
            found += 1
    assert found > 0, "mock should exercise at least one advisory"


def test_lead_dates_are_contiguous_7_day_windows(generated):
    ld = generated["meta"]["lead_dates"]
    for lead in c.LEADS:
        start = date.fromisoformat(ld[lead]["start"])
        end = date.fromisoformat(ld[lead]["end"])
        assert (end - start).days == 6
    assert (date.fromisoformat(ld["w2"]["start"])
            - date.fromisoformat(ld["w1"]["end"])).days == 1


def test_mock_is_labelled_as_mock(generated):
    """Nothing invented may masquerade as real output."""
    assert generated["meta"]["is_mock"] is True
    assert generated["meta"]["code_system"] == "mock"
    assert "mock" in generated["meta"]["model_version"]


def test_skill_is_present_and_can_be_negative(generated):
    """Honest verification is carried in the payload so the UI cannot hide it."""
    bss = generated["skill"]["bss"]
    assert set(bss) == set(c.LEADS)
    assert bss["w1"] > bss["w4"], "skill must decay with lead time"
    assert generated["skill"]["reference"]
    assert 1 <= generated["skill"]["advisory_horizon_weeks"] <= 4


# --- the schema must REJECT bad data -------------------------------------


def _mutate(payload, fn):
    p = deepcopy(payload)
    fn(p)
    return p


@pytest.mark.parametrize(
    "name,mutate",
    [
        ("probability above 1",
         lambda p: p["areas"]["MOCK-BLK-Tumakuru"]["p_dry7"].__setitem__("w1", 1.4)),
        ("negative probability",
         lambda p: p["areas"]["MOCK-BLK-Tumakuru"]["p_onset"].__setitem__("w2", -0.1)),
        ("missing lead week",
         lambda p: p["areas"]["MOCK-BLK-Tumakuru"]["p_heavy"].pop("w3")),
        ("advisory without citation",
         lambda p: p["areas"]["MOCK-BLK-Tumakuru"]["advisories"][0].pop("source")),
        ("advisory without Kannada",
         lambda p: p["areas"]["MOCK-BLK-Tumakuru"]["advisories"][0].pop("action_kn")),
        ("more than 3 advisories",
         lambda p: p["areas"]["MOCK-BLK-Tumakuru"].__setitem__(
             "advisories", p["areas"]["MOCK-BLK-Tumakuru"]["advisories"] * 4)),
        ("unknown onset status",
         lambda p: p["areas"]["MOCK-BLK-Tumakuru"].__setitem__("onset_status", "raining_hard")),
        ("undeclared extra field",
         lambda p: p["areas"]["MOCK-BLK-Tumakuru"].__setitem__("p_cyclone", {"w1": 0.1})),
        ("areas as a list instead of a map",
         lambda p: p.__setitem__("areas", list(p["areas"].values()))),
        ("n_cells zero",
         lambda p: p["areas"]["MOCK-BLK-Tumakuru"].__setitem__("n_cells", 0)),
        ("missing skill block", lambda p: p.pop("skill")),
    ],
)
def test_schema_rejects(generated, name, mutate):
    bad = _mutate(generated, mutate)
    with pytest.raises(c.ContractError):
        c.validate(bad, "forecast.schema.json")


def test_leadset_builder_rejects_out_of_range():
    with pytest.raises(c.ContractError):
        c.leadset(0.5, 0.5, 0.5, 1.7)


def test_write_json_enforces_size_budget(tmp_path):
    big = {"x": "y" * 5000}
    with pytest.raises(c.ContractError):
        c.write_json(big, tmp_path / "big.json", max_bytes=c.AREA_FILE_MAX_BYTES)


# --- scale check ----------------------------------------------------------


def test_projected_full_karnataka_size_is_sane(generated):
    """~240 taluks + ~750 hoblis. latest.json must stay servable; farmer files are per-area."""
    per_area = len(json.dumps(generated["areas"]["MOCK-BLK-Tiptur"]).encode())
    projected = per_area * 990 / 1024
    assert projected < 1500, f"latest.json would be ~{projected:.0f} KB at full scale"
