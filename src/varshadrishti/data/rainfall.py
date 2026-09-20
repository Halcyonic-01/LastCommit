"""Daily rainfall from three sources behind one interface.

All three return a DataFrame indexed by date, one column per cell_id, in mm:

  imd     0.25 deg, 1991-2024  - primary training truth (official MoES reference)
  era5    0.25 deg cells        - fallback if IMD Pune is unavailable
  chirps  0.05 deg, seasons     - panchayat-scale verification layer

Same shape means the downstream label and feature code does not care which one it got.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw"

MISSING = -999.0  # IMD's sea/no-data flag; masking with `< 1000` KEEPS it

# Cells the Karnataka weight matrices name but IMD never fills - the 0.25 deg grid treats
# them as sea. They appear in 4 of 1,127 areas and the aggregator renormalises over the
# cells that remain, so the only thing they can corrupt is a published `n_cells`.
IMD_NO_DATA_CELLS = frozenset({"imd:14.75:74.0"})


def _cell_id(grid: str, lat: float, lon: float) -> str:
    return f"{grid}:{round(lat, 4)}:{round(lon, 4)}"


def load_imd(start: int, end: int, bounds=None) -> pd.DataFrame:
    """IMD 0.25 deg gridded daily rainfall, wide by cell_id."""
    import imdlib as imd

    frames = []
    for year in range(start, end + 1):
        ds = imd.open_data("rain", year, year, "yearwise", file_dir=str(RAW)).get_xarray()
        da = ds["rain"].where(ds["rain"] >= 0)  # never `< 1000` — that keeps -999
        if bounds:
            minx, miny, maxx, maxy = bounds
            da = da.sel(lat=slice(miny, maxy), lon=slice(minx, maxx))
        df = da.to_dataframe(name="mm").reset_index()
        df["cell_id"] = [
            _cell_id("imd", la, lo) for la, lo in zip(df["lat"], df["lon"])
        ]
        frames.append(df.pivot_table(index="time", columns="cell_id", values="mm"))
        ds.close()
    return pd.concat(frames).sort_index()


def load_era5() -> pd.DataFrame:
    """ERA5-Land fallback, reassembled from the cached archive chunks."""
    chunks = sorted((RAW / "era5").glob("*.json"))
    if not chunks:
        raise FileNotFoundError("no ERA5 chunks — run scripts/download_era5_insurance.py")

    parts = []
    for path in chunks:
        blob = json.loads(path.read_text())
        cols = {}
        for cell_id, item in zip(blob["cell_ids"], blob["data"]):
            daily = item["daily"]
            cols[cell_id] = pd.Series(
                daily["precipitation_sum"], index=pd.to_datetime(daily["time"])
            )
        parts.append(pd.DataFrame(cols))

    # chunks tile both axes: concat down time, then merge columns per period
    by_period = {}
    for path, part in zip(chunks, parts):
        key = path.stem.rsplit("_b", 1)[0]
        by_period.setdefault(key, []).append(part)
    merged = [pd.concat(v, axis=1) for v in by_period.values()]
    return pd.concat(merged).sort_index()


def load_chirps(start: int, end: int) -> pd.DataFrame:
    """CHIRPS 0.05 deg seasons, wide by cell_id. Much wider than IMD - 12,880 cells."""
    import xarray as xr

    frames = []
    for year in range(start, end + 1):
        p = RAW / "chirps" / f"chirps_karnataka_{year}.nc"
        if not p.exists():
            continue
        da = xr.open_dataset(p)["precip"]
        da = da.where(da >= 0)
        df = da.to_dataframe(name="mm").reset_index()
        df["cell_id"] = [
            _cell_id("chirps", la, lo) for la, lo in zip(df["latitude"], df["longitude"])
        ]
        frames.append(df.pivot_table(index="time", columns="cell_id", values="mm"))
        da.close()
    if not frames:
        raise FileNotFoundError(f"no CHIRPS seasons in {start}-{end}")
    return pd.concat(frames).sort_index()


def season(df: pd.DataFrame, year: int, start_md="06-01", end_md="09-30") -> pd.DataFrame:
    return df.loc[f"{year}-{start_md}":f"{year}-{end_md}"]


def available_sources() -> dict[str, bool]:
    return {
        "imd": len(list((RAW / "rain").glob("*.grd"))) >= 30,
        "era5": len(list((RAW / "era5").glob("*.json"))) >= 200,
        "chirps": len(list((RAW / "chirps").glob("*.nc"))) >= 30,
    }
