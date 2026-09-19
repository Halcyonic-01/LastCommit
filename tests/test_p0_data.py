"""P0 acceptance: every dataset downloaded, readable and sane."""

import json
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

IMD_LAT, IMD_LON = 129, 135  # 6.5-38.5N, 66.5-100.0E at 0.25 deg
YEARS = range(1991, 2025)

# A fresh clone has no data/raw — it is all gitignored and re-downloadable. Skip with the
# command to fix it rather than failing 23 times at a new teammate.
pytestmark = pytest.mark.skipif(
    not list(RAW.joinpath("rain").glob("*.grd")),
    reason="no IMD data — run `.venv/bin/python scripts/download_imd.py` (825 MB, ~13 min)",
)


def test_all_34_years_present():
    grds = sorted(RAW.joinpath("rain").glob("*.grd"))
    assert len(grds) == 34, f"expected 34 years, found {len(grds)}"
    got = {int(p.stem) for p in grds}
    assert got == set(YEARS), f"missing: {set(YEARS) - got}"


@pytest.mark.parametrize("year", [1991, 2008, 2024])
def test_grd_file_size_matches_grid(year):
    # days x 129 lat x 135 lon x 4-byte float, exactly
    days = 366 if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0 else 365
    expected = days * IMD_LAT * IMD_LON * 4
    actual = RAW.joinpath("rain", f"{year}.grd").stat().st_size
    assert actual == expected, f"{year}: {actual} != {expected}"


def test_imd_grid_reads_with_correct_dims():
    import imdlib as imd

    ds = imd.open_data("rain", 2023, 2023, "yearwise", file_dir=str(RAW)).get_xarray()
    assert ds.sizes["lat"] == IMD_LAT
    assert ds.sizes["lon"] == IMD_LON
    assert ds.sizes["time"] == 365
    assert float(ds.lat.min()) == pytest.approx(6.5)
    assert float(ds.lat.max()) == pytest.approx(38.5)
    assert float(ds.lon.min()) == pytest.approx(66.5)
    assert float(ds.lon.max()) == pytest.approx(100.0)


def test_tumakuru_2023_rainfall_is_plausible():
    import imdlib as imd

    ds = imd.open_data("rain", 2023, 2023, "yearwise", file_dir=str(RAW)).get_xarray()
    cell = ds["rain"].sel(lat=13.25, lon=77.0, method="nearest")
    jjas = cell.where(cell < 1000).sel(time=slice("2023-06-01", "2023-09-30"))

    total = float(jjas.sum())
    rainy = int((jjas >= 2.5).sum())
    # 2023 was the El Nino year Karnataka declared drought in 223 taluks
    assert 150 < total < 900, f"JJAS total {total:.0f} mm outside plausible range"
    assert 15 < rainy < 90, f"{rainy} rainy days outside plausible range"


def test_missing_value_mask_must_be_ge_zero():
    import imdlib as imd

    ds = imd.open_data("rain", 2023, 2023, "yearwise", file_dir=str(RAW)).get_xarray()
    rain = ds["rain"]

    # sea cells carry -999. `< 1000` KEEPS them and would poison rolling sums at P4.
    assert float(rain.where(rain < 1000).min()) == pytest.approx(-999.0)

    # `>= 0` is the correct mask — use this everywhere downstream.
    assert float(rain.where(rain >= 0).min()) >= 0.0


@pytest.mark.parametrize(
    "name,min_lines", [("oni.txt", 70), ("nino34.txt", 70), ("dmi.txt", 150), ("rmm_mjo.txt", 18000)]
)
def test_indices_downloaded(name, min_lines):
    p = RAW / "indices" / name
    assert p.exists(), f"{name} missing"
    assert p.read_text(errors="ignore").count("\n") >= min_lines


def test_rmm_has_all_four_mjo_columns():
    rows = (RAW / "indices" / "rmm_mjo.txt").read_text(errors="ignore").splitlines()
    data = [r.split() for r in rows[2:] if r.strip()]
    assert len(data) > 18000
    assert len(data[-1]) >= 7, "expect year month day RMM1 RMM2 phase amplitude"


@pytest.mark.parametrize(
    "pdf",
    [
        "KA_Tumakuru.pdf",
        "KA_Chitradurga.pdf",
        "KA_Chikkaballapur.pdf",
        "KA_Davanagere.pdf",
        "KA_Kolar.pdf",
        "MH_Yavatmal_Vidarbha.pdf",
    ],
)
def test_crida_plans_present_and_valid(pdf):
    p = RAW / "crida" / pdf
    assert p.exists(), f"{pdf} missing"
    assert p.stat().st_size > 100_000, f"{pdf} suspiciously small"
    assert p.read_bytes()[:4] == b"%PDF"


@pytest.mark.network
def test_ec46_still_serves_46_days_and_50_members():
    url = (
        "https://seasonal-api.open-meteo.com/v1/seasonal"
        "?latitude=13.34&longitude=77.10&daily=precipitation_sum&forecast_days=46"
    )
    daily = json.load(urllib.request.urlopen(url, timeout=60))["daily"]
    members = [k for k in daily if k.startswith("precipitation_sum_member")]
    assert len(daily["time"]) == 46
    assert len(members) >= 50


CHIRPS = RAW / "chirps"


def test_chirps_years_present():
    files = sorted(CHIRPS.glob("chirps_karnataka_*.nc"))
    assert len(files) >= 1, "no CHIRPS seasons downloaded"


def test_chirps_is_higher_resolution_than_imd():
    import xarray as xr

    f = sorted(CHIRPS.glob("chirps_karnataka_*.nc"))[-1]
    d = xr.open_dataset(f)["precip"]
    res = abs(float(d.latitude[1] - d.latitude[0]))
    assert res == pytest.approx(0.05, abs=1e-3), f"expected 0.05 deg, got {res}"
    cells = d.sizes["latitude"] * d.sizes["longitude"]
    assert cells > 10000, f"only {cells} cells; expected ~12,880 over Karnataka"


def test_chirps_resolves_variation_inside_one_imd_cell():
    """The PS's premise, measured: block averaging hides panchayat variation."""
    import xarray as xr

    f = sorted(CHIRPS.glob("chirps_karnataka_*.nc"))[-1]
    d = xr.open_dataset(f)["precip"]
    d = d.where(d >= 0)
    # one 0.25 deg IMD cell around Tumakuru
    sub = d.sel(latitude=slice(13.25, 13.50), longitude=slice(77.00, 77.25)).sum("time")
    assert sub.sizes["latitude"] >= 5 and sub.sizes["longitude"] >= 5
    spread = float(sub.max() - sub.min())
    assert spread > 50, f"only {spread:.0f} mm spread inside one IMD cell"


def test_chirps_has_no_negative_rainfall_after_masking():
    import xarray as xr

    f = sorted(CHIRPS.glob("chirps_karnataka_*.nc"))[-1]
    d = xr.open_dataset(f)["precip"]
    assert float(d.where(d >= 0).min()) >= 0.0
