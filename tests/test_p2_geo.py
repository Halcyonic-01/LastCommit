"""P2 acceptance: boundaries are clean, weights are sound, the P1 contract still holds."""

import json
import sys
import warnings
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

from varshadrishti import contract as c  # noqa: E402
from varshadrishti.geo import boundaries as B  # noqa: E402
from varshadrishti.geo import weights as W  # noqa: E402

GEO = ROOT / "geo"
PROC = ROOT / "data" / "processed"
KA_BOUNDS = (74.0, 11.5, 78.7, 18.5)  # minx, miny, maxx, maxy

pytestmark = pytest.mark.skipif(
    not (GEO / "blocks.geojson").exists(), reason="run scripts/build_geo.py first"
)


@pytest.fixture(scope="module")
def blocks():
    import geopandas as gpd
    return gpd.read_file(GEO / "blocks.geojson")


@pytest.fixture(scope="module")
def hoblis():
    import geopandas as gpd
    return gpd.read_file(GEO / "hoblis.geojson")


@pytest.fixture(scope="module")
def districts():
    import geopandas as gpd
    return gpd.read_file(GEO / "districts.geojson")


# --- boundaries -----------------------------------------------------------


def test_area_ids_are_unique(blocks, hoblis):
    """KGIS ships multipart areas as separate rows; they must be dissolved."""
    for g, name in ((blocks, "blocks"), (hoblis, "hoblis")):
        dupes = g["area_id"].duplicated().sum()
        assert dupes == 0, f"{name}: {dupes} duplicate area_id"


def test_expected_counts(districts, blocks, hoblis):
    assert len(districts) == 30, f"expected 30 districts, got {len(districts)}"
    assert len(blocks) == 227, f"expected 227 taluks, got {len(blocks)}"
    assert len(hoblis) == 870, f"expected 870 hoblis, got {len(hoblis)}"


def test_geojson_under_1mb():
    for name in ("districts", "blocks", "hoblis"):
        size = (GEO / f"{name}.geojson").stat().st_size
        assert size < 1_000_000, f"{name}.geojson is {size / 1024:.0f} KB"


def test_geometries_are_valid_and_nonempty(blocks, hoblis):
    for g, name in ((blocks, "blocks"), (hoblis, "hoblis")):
        assert (~g.geometry.is_valid).sum() == 0, f"{name} has invalid geometry"
        assert g.geometry.is_empty.sum() == 0, f"{name} has empty geometry"


def test_everything_lies_within_karnataka(blocks, hoblis):
    minx, miny, maxx, maxy = KA_BOUNDS
    for g, name in ((blocks, "blocks"), (hoblis, "hoblis")):
        b = g.total_bounds
        assert b[0] >= minx - 0.5 and b[1] >= miny - 0.5, f"{name} extends SW of Karnataka"
        assert b[2] <= maxx + 0.5 and b[3] <= maxy + 0.5, f"{name} extends NE of Karnataka"


def test_every_hobli_parent_is_a_real_block(blocks, hoblis):
    valid = set(blocks["area_id"])
    orphans = set(hoblis["parent_id"]) - valid
    assert not orphans, f"{len(orphans)} hoblis point at a missing taluk: {sorted(orphans)[:5]}"


def test_lgd_crosswalk_is_partial_and_honest(blocks):
    """LGD's Karnataka list predates recent taluk splits — a null code is correct, a guess is not."""
    matched = blocks["lgd_code"].notna().sum()
    assert matched > 100, f"only {matched} LGD matches — crosswalk broke"
    assert matched < len(blocks), "full match is implausible; check for fuzzy over-matching"


# --- weights --------------------------------------------------------------


@pytest.mark.parametrize("grid", ["imd", "chirps"])
@pytest.mark.parametrize("level", ["districts", "blocks", "hoblis"])
def test_weights_sum_to_one_per_area(grid, level):
    w = pd.read_parquet(PROC / f"weights_{grid}_{level}.parquet")
    sums = w.groupby("area_id")["weight"].sum()
    assert sums.between(0.9999, 1.0001).all(), (
        f"{grid}/{level}: worst row sums to {sums.min():.6f} / {sums.max():.6f}"
    )


@pytest.mark.parametrize("grid", ["imd", "chirps"])
@pytest.mark.parametrize("level", ["districts", "blocks", "hoblis"])
def test_no_area_maps_to_zero_cells(grid, level):
    import geopandas as gpd

    w = pd.read_parquet(PROC / f"weights_{grid}_{level}.parquet")
    g = gpd.read_file(GEO / f"{level}.geojson")
    missing = set(g["area_id"]) - set(w["area_id"])
    assert not missing, f"{grid}/{level}: {len(missing)} areas have no grid coverage"


@pytest.mark.parametrize("grid", ["imd", "chirps"])
@pytest.mark.parametrize("level", ["districts", "blocks", "hoblis"])
def test_weights_are_positive_fractions(grid, level):
    w = pd.read_parquet(PROC / f"weights_{grid}_{level}.parquet")
    assert w["weight"].gt(0).all()
    assert w["weight"].le(1.0 + 1e-9).all()


def test_chirps_resolves_more_cells_per_hobli_than_imd():
    """The quantitative case for the panchayat-scale claim."""
    imd = W.cells_per_area(pd.read_parquet(PROC / "weights_imd_hoblis.parquet"))
    chirps = W.cells_per_area(pd.read_parquet(PROC / "weights_chirps_hoblis.parquet"))
    assert chirps.median() >= 4 * imd.median(), (
        f"CHIRPS median {chirps.median()} vs IMD {imd.median()}"
    )


def test_imd_resolution_collapses_most_hoblis_together():
    """At 0.25 deg most hoblis share a dominant cell, so they'd get identical forecasts."""
    def collision_rate(path):
        w = pd.read_parquet(path)
        dom = w.sort_values("weight", ascending=False).groupby("area_id").first()
        shared = dom.groupby("cell_id").size()
        return int(shared[shared > 1].sum()) / len(dom)

    imd = collision_rate(PROC / "weights_imd_hoblis.parquet")
    chirps = collision_rate(PROC / "weights_chirps_hoblis.parquet")
    assert imd > 0.80, f"expected IMD collisions >80%, got {imd:.0%}"
    assert chirps < 0.15, f"expected CHIRPS collisions <15%, got {chirps:.0%}"


def test_grid_cells_align_to_imd_lattice():
    """Cell centres must sit on IMD's own lattice or aggregation silently misaligns."""
    cells = W.grid_cells("imd", KA_BOUNDS)
    off_lat = ((cells["lat"] - 6.5) % 0.25).abs()
    off_lon = ((cells["lon"] - 66.5) % 0.25).abs()
    assert (off_lat.lt(1e-6) | off_lat.gt(0.25 - 1e-6)).all()
    assert (off_lon.lt(1e-6) | off_lon.gt(0.25 - 1e-6)).all()


def test_aggregate_computes_weighted_mean():
    w = pd.DataFrame({
        "area_id": ["A", "A", "B"],
        "cell_id": ["c1", "c2", "c1"],
        "lat": [0, 0, 0], "lon": [0, 0, 0],
        "weight": [0.75, 0.25, 1.0],
    })
    values = pd.Series({"c1": 100.0, "c2": 200.0})
    out = W.aggregate(values, w)
    assert out["A"] == pytest.approx(125.0)  # 0.75*100 + 0.25*200
    assert out["B"] == pytest.approx(100.0)


def test_aggregate_renormalises_when_cells_are_missing():
    """Sea cells and no-data cells drop out; the remaining weights must still sum to 1."""
    w = pd.DataFrame({
        "area_id": ["A", "A"],
        "cell_id": ["c1", "c2"],
        "lat": [0, 0], "lon": [0, 0],
        "weight": [0.6, 0.4],
    })
    out = W.aggregate(pd.Series({"c1": 50.0}), w)  # c2 absent
    assert out["A"] == pytest.approx(50.0), "missing cell must not drag the mean toward zero"


# --- the P1 contract must still hold with real ids ------------------------


def test_real_ids_still_satisfy_the_p1_contract():
    """The P2 handoff: ids changed from MOCK-* to KGIS-*, the shape did not."""
    latest = c.load_and_validate(ROOT / "forecast" / "latest.json", "forecast.schema.json")
    assert latest["meta"]["code_system"] == "kgis"
    assert len(latest["areas"]) > 1000
    assert all(a.startswith("KGIS-") for a in latest["areas"])


def test_forecast_areas_match_the_geojson(districts, blocks, hoblis):
    latest = json.loads((ROOT / "forecast" / "latest.json").read_text())
    geo_ids = set(districts["area_id"]) | set(blocks["area_id"]) | set(hoblis["area_id"])
    assert set(latest["areas"]) == geo_ids, "map and forecast disagree on which areas exist"


def test_n_cells_counts_only_cells_that_carry_data():
    """A cell the matrix names but IMD never fills is not coverage.

    `imd:14.75:74.0` is sea. It sits in 4 of 1,127 areas, and counting it overstated
    KGIS-D-10 at 26 cells when 25 of them carry rainfall. The aggregator already
    renormalises over the live cells, so the published count has to agree with it.
    """
    from varshadrishti.data import rainfall as R
    from varshadrishti.geo import weights as W

    latest = json.loads((ROOT / "forecast" / "latest.json").read_text())
    w = pd.concat([
        pd.read_parquet(PROC / f"weights_imd_{lvl}.parquet")
        for lvl in ("districts", "blocks", "hoblis")
    ])
    counts = W.coverage(w, R.IMD_NO_DATA_CELLS)["n_cells"].to_dict()
    for aid, body in list(latest["areas"].items())[:200]:
        assert body["n_cells"] == counts[aid], f"{aid}: n_cells is not the real count"


def test_no_area_is_left_with_zero_cells_after_excluding_no_data():
    """Excluding sea cells must not strand an area with nothing to aggregate over."""
    from varshadrishti.data import rainfall as R
    from varshadrishti.geo import weights as W

    for lvl in ("districts", "blocks", "hoblis"):
        cov = W.coverage(pd.read_parquet(PROC / f"weights_imd_{lvl}.parquet"),
                         R.IMD_NO_DATA_CELLS)
        empty = cov[cov["n_cells"] == 0]
        assert empty.empty, f"{lvl}: {list(empty.index)} lost every cell"
        assert cov["weight_lost"].max() < 0.10, f"{lvl}: an area lost >10% of its weight"


def test_farmer_payloads_still_within_budget():
    files = list((ROOT / "forecast" / "area").glob("*.json"))
    assert len(files) > 1000
    worst = max(f.stat().st_size for f in files)
    assert worst <= c.AREA_FILE_MAX_BYTES, f"largest farmer payload is {worst} B"


def test_no_nan_leaked_into_json():
    """pandas NaN serialises as bare NaN, which is not valid JSON."""
    blob = (ROOT / "forecast" / "latest.json").read_text()
    assert "NaN" not in blob and "Infinity" not in blob


def test_split_forecast_reproduces_generator_output(tmp_path):
    """The Vercel build step must produce exactly what the pipeline would have written."""
    import shutil
    import subprocess

    shutil.copy(ROOT / "forecast" / "latest.json", tmp_path / "latest.json")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "split_forecast.py"),
         "--forecast-dir", str(tmp_path)],
        check=True, capture_output=True,
    )
    rebuilt = list((tmp_path / "area").glob("*.json"))
    original = list((ROOT / "forecast" / "area").glob("*.json"))
    assert len(rebuilt) == len(original)

    for f in rebuilt[:100]:
        assert f.read_bytes() == (ROOT / "forecast" / "area" / f.name).read_bytes(), f.name


# --- gap-audit regressions (found auditing P0-P2) --------------------------


def test_hierarchy_resolves_hobli_to_taluk_to_district():
    """Onboarding is district -> taluk -> hobli; every link must resolve."""
    A = json.loads((ROOT / "forecast" / "latest.json").read_text())["areas"]
    hoblis = [a for a in A.values() if a["level"] == "panchayat"]
    assert hoblis
    for h in hoblis:
        taluk = A.get(h["parent_id"])
        assert taluk and taluk["level"] == "block", f"{h['name_en']}: broken taluk link"
        dist = A.get(taluk["parent_id"])
        assert dist and dist["level"] == "district", f"{taluk['name_en']}: broken district link"


def test_district_en_is_a_real_district_name(districts):
    """It was previously the taluk's own name — a silent join bug."""
    A = json.loads((ROOT / "forecast" / "latest.json").read_text())["areas"]
    valid = set(districts["name_en"])
    for a in A.values():
        if a["level"] in ("block", "panchayat"):
            assert a["district_en"] in valid, f"{a['name_en']}: district_en={a['district_en']!r}"


def test_taluks_carved_into_newer_districts_are_filed_correctly():
    """KGISDistri is a ROW id, not a district code; the taluk-code prefix disagrees for 17
    taluks including all of Chikkaballapura, a pilot district."""
    A = json.loads((ROOT / "forecast" / "latest.json").read_text())["areas"]
    by_name = {a["name_en"].upper(): a for a in A.values() if a["level"] == "block"}
    for n in ("GAURIBIDANUR", "CHIKBALLAPUR", "GUDIBANDE", "BAGEPALLI", "SHIDLAGATTA"):
        assert by_name[n]["district_en"] == "Chikkaballapura", (
            f"{n} filed under {by_name[n]['district_en']}"
        )


def test_kannada_names_present_for_districts_and_taluks():
    """Farmer UI is Kannada-first. Hoblis have no OSM coverage and fall back to English."""
    A = json.loads((ROOT / "forecast" / "latest.json").read_text())["areas"]
    d = [a for a in A.values() if a["level"] == "district"]
    b = [a for a in A.values() if a["level"] == "block"]
    assert sum(1 for a in d if a.get("name_kn")) >= 25, "district Kannada coverage dropped"
    assert sum(1 for a in b if a.get("name_kn")) >= 150, "taluk Kannada coverage dropped"


def test_kannada_names_are_actually_kannada_script():
    """Guards against a transliterator emitting Latin or broken glyphs."""
    A = json.loads((ROOT / "forecast" / "latest.json").read_text())["areas"]
    for a in A.values():
        kn = a.get("name_kn")
        if kn:
            assert any("\u0c80" <= ch <= "\u0cff" for ch in kn), f"{a['name_en']}: {kn!r}"


def test_ec46_response_is_cached_for_outage_resilience():
    """The risk register's mitigation — without a cached run, an outage kills the demo."""
    cache = sorted((ROOT / "data" / "cache" / "ec46").glob("*.json"))
    assert cache, "no EC46 response cached"
    blob = json.loads(cache[-1].read_text())
    assert blob["members"] >= 50, f"only {blob['members']} members cached"
    assert blob["forecast_days"] == 46
    assert len(blob["cells"]) > 300, f"only {len(blob['cells'])} cells cached"
    one = next(iter(blob["cells"].values()))
    assert len(one["time"]) == 46 and len(one["members"]) >= 50


def test_served_sizes_are_within_budget_gzipped():
    """Vercel serves gzip — raw bytes were the wrong metric for the wire budget."""
    import gzip

    budgets = {
        "forecast/index.json": 30_000,
        "forecast/latest.json": 120_000,
        "geo/hoblis.geojson": 400_000,
    }
    for rel, cap in budgets.items():
        wire = len(gzip.compress((ROOT / rel).read_bytes()))
        assert wire <= cap, f"{rel} is {wire:,} B gzipped, cap {cap:,}"
