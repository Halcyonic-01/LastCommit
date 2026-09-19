"""Fallback and model-diversity coverage: ERA5 insurance, CHIRPS depth, GEFS second NWP."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "cache"
ERA5 = RAW / "era5"
CHIRPS = RAW / "chirps"

IMD_YEARS = range(1991, 2025)
ERA5_CHUNKS_EXPECTED = 238  # 324 cells / batch 50, x 34 season windows

needs_era5 = pytest.mark.skipif(
    len(list(ERA5.glob("*.json"))) < ERA5_CHUNKS_EXPECTED,
    reason=(
        f"ERA5 backfill incomplete ({len(list(ERA5.glob('*.json')))}/{ERA5_CHUNKS_EXPECTED} "
        "chunks) — bounded by Open-Meteo's hourly cap, not by the code. "
        "Run scripts/run_era5_until_done.sh"
    ),
)


# --- CHIRPS depth ---------------------------------------------------------


def test_chirps_matches_imd_season_coverage():
    """CHIRPS is the panchayat-scale verification layer; it must span the IMD training years."""
    years = {int(p.stem.rsplit("_", 1)[1]) for p in CHIRPS.glob("chirps_karnataka_*.nc")}
    missing = set(IMD_YEARS) - years
    assert not missing, f"{len(missing)} seasons missing: {sorted(missing)[:8]}"


def test_chirps_seasons_all_have_the_same_shape():
    import xarray as xr

    shapes = set()
    for p in sorted(CHIRPS.glob("chirps_karnataka_*.nc")):
        d = xr.open_dataset(p)["precip"]
        shapes.add((d.sizes["latitude"], d.sizes["longitude"]))
        d.close()
    assert len(shapes) == 1, f"inconsistent grids across seasons: {shapes}"
    assert shapes.pop() == (140, 92)


# --- ERA5 insurance -------------------------------------------------------


@pytest.fixture(scope="module")
def era5_chunks():
    return sorted(ERA5.glob("*.json"))


@needs_era5
def test_era5_covers_every_cell_and_period(era5_chunks):
    """Insurance that was never proven at scale is not insurance."""
    assert era5_chunks, "no ERA5 chunks — run scripts/download_era5_insurance.py"
    # Chunked per SEASON, not per 5-year block: the archive API weights a call by
    # locations x time range, and whole-year windows kept tripping the hourly cap.
    periods, cells = set(), set()
    for p in era5_chunks:
        d = json.loads(p.read_text())
        periods.add((d["start"], d["end"]))
        cells.update(d["cell_ids"])
    seasons = {pd.Timestamp(a).year for a, _ in periods}
    assert seasons == set(range(1991, 2025)), f"missing seasons: {set(range(1991,2025)) - seasons}"
    for a, b in periods:
        assert pd.Timestamp(a).month == 5 and pd.Timestamp(b).month == 10, (a, b)

    w = pd.concat([pd.read_parquet(p) for p in (ROOT / "data" / "processed").glob("weights_imd_*.parquet")])
    expected = set(w["cell_id"].unique())
    assert cells == expected, f"{len(expected - cells)} cells missing from ERA5 fallback"


@needs_era5
def test_era5_values_are_plausible_rainfall(era5_chunks):
    d = json.loads(era5_chunks[-1].read_text())
    series = d["data"][0]["daily"]["precipitation_sum"]
    vals = [v for v in series if v is not None]
    assert vals, "empty ERA5 series"
    assert min(vals) >= 0, "negative rainfall"
    assert max(vals) < 1000, f"implausible daily max {max(vals)} mm"


@needs_era5
def test_era5_can_substitute_for_imd_on_the_same_cell(era5_chunks):
    """The point of the fallback: same cell, same season, comparable seasonal total."""
    import imdlib as imd

    year = 2023
    chunk = next((p for p in era5_chunks if p.name.startswith(f"{year}_")), None)
    assert chunk, f"no {year} ERA5 chunk"
    d = json.loads(chunk.read_text())

    cell_id = d["cell_ids"][0]
    _, lat, lon = cell_id.split(":")
    lat, lon = float(lat), float(lon)

    item = d["data"][0]["daily"]
    era = pd.Series(item["precipitation_sum"], index=pd.to_datetime(item["time"]))
    era_jjas = float(era[f"{year}-06-01":f"{year}-09-30"].fillna(0).sum())

    ds = imd.open_data("rain", year, year, "yearwise", file_dir=str(RAW)).get_xarray()
    cell = ds["rain"].sel(lat=lat, lon=lon, method="nearest")
    imd_jjas = float(cell.where(cell >= 0).sel(time=slice(f"{year}-06-01", f"{year}-09-30")).sum())

    assert era_jjas > 0 and imd_jjas > 0
    ratio = era_jjas / imd_jjas
    # different products; agreement within a factor of ~2.5 means the fallback is usable
    assert 0.4 < ratio < 2.5, (
        f"ERA5 {era_jjas:.0f} mm vs IMD {imd_jjas:.0f} mm at {lat},{lon} — ratio {ratio:.2f}"
    )


# --- NWP model diversity --------------------------------------------------


@pytest.mark.parametrize(
    "model,days,members", [("ec46", 46, 50), ("gefs", 35, 30)]
)
def test_nwp_model_cached(model, days, members):
    files = sorted((CACHE / model).glob("*.json"))
    assert files, f"no {model} response cached"
    blob = json.loads(files[-1].read_text())
    assert blob["forecast_days"] == days
    assert blob["members"] >= members, f"{model}: {blob['members']} members"
    assert len(blob["cells"]) > 300
    one = next(iter(blob["cells"].values()))
    assert len(one["time"]) == days
    assert len(one["members"]) >= members


def test_two_independent_nwp_models_are_available():
    """The blend's model-diversity claim needs a genuine second model, not a second run."""
    models = {p.name for p in CACHE.iterdir() if p.is_dir() and any(p.glob("*.json"))}
    assert {"ec46", "gefs"} <= models, f"only have {models}"


def test_nwp_models_cover_the_same_cells():
    ec = json.loads(sorted((CACHE / "ec46").glob("*.json"))[-1].read_text())["cells"]
    gf = json.loads(sorted((CACHE / "gefs").glob("*.json"))[-1].read_text())["cells"]
    assert set(ec) == set(gf), "EC46 and GEFS disagree on cell coverage — cannot blend"


# --- one interface over three sources -------------------------------------


def test_chirps_loader_returns_wide_daily_frame():
    from varshadrishti.data import rainfall as R

    c = R.load_chirps(2025, 2025)
    assert c.shape[0] == 153, f"expected 153 season days, got {c.shape[0]}"
    assert c.shape[1] > 10_000, f"expected >10k CHIRPS cells, got {c.shape[1]}"
    assert c.min().min() >= 0, "negative rainfall survived masking"


@needs_era5
def test_era5_loader_reassembles_every_cell():
    from varshadrishti.data import rainfall as R

    e = R.load_era5()
    assert e.shape[1] == 324, f"expected 324 cells, got {e.shape[1]}"
    assert e.index.is_monotonic_increasing
    assert not e.index.has_duplicates, "chunks overlap in time"


@needs_era5
def test_era5_loader_spans_the_imd_training_years():
    from varshadrishti.data import rainfall as R

    e = R.load_era5()
    assert e.index.min().year <= 1991
    assert e.index.max().year >= 2024


def test_imd_and_chirps_are_complete():
    """IMD and CHIRPS are the two sources the model actually depends on."""
    from varshadrishti.data import rainfall as R

    avail = R.available_sources()
    assert avail["imd"], "IMD incomplete"
    assert avail["chirps"], "CHIRPS incomplete"


@needs_era5
def test_all_three_sources_present():
    from varshadrishti.data import rainfall as R

    assert all(R.available_sources().values())
