"""Pull CHIRPS 0.05deg daily rainfall over Karnataka — the panchayat-scale truth layer.

Replaces the KSNDMC hobli gauge request (email-gated, ~10 day turnaround).
CHIRPS is 0.05deg (~5.5 km) vs IMD's 0.25deg (~27.5 km): 12,880 cells over
Karnataka instead of ~300, which is what makes hobli-scale verification possible.

IMD stays the primary training truth (official MoES reference). CHIRPS is the
downscaling and verification layer.
"""

import argparse
import sys
import time
from pathlib import Path

import fsspec
import xarray as xr

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "chirps"
URL = (
    "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p05/"
    "chirps-v2.0.{year}.days_p05.nc"
)

LAT0, LAT1 = 11.5, 18.5
LON0, LON1 = 74.0, 78.6
BLOCK = 2**23  # 8 MB reads; chunks are (20, 112, 400) gzip


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pull_year(year, start_md, end_md):
    dest = OUT / f"chirps_karnataka_{year}.nc"
    if dest.exists() and dest.stat().st_size > 100_000:
        log(f"{year} already on disk, skipping")
        return True

    t = time.time()
    f = fsspec.open(URL.format(year=year), mode="rb", block_size=BLOCK).open()
    ds = xr.open_dataset(f, engine="h5netcdf")
    win = ds["precip"].sel(
        latitude=slice(LAT0, LAT1),
        longitude=slice(LON0, LON1),
        time=slice(f"{year}-{start_md}", f"{year}-{end_md}"),
    )
    win.load()  # force the range requests now
    win.to_netcdf(dest)
    ds.close()
    log(
        f"{year} {dict(win.sizes)} -> {dest.stat().st_size / 1e6:.1f} MB "
        f"in {time.time() - t:.0f}s"
    )
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2015)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--season", default="06-01:10-31")  # JJAS + withdrawal
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    start_md, end_md = args.season.split(":")
    t0 = time.time()
    failed = []

    for year in range(args.start, args.end + 1):
        for attempt in (1, 2, 3, 4):  # CHC resets connections on large range reads
            try:
                pull_year(year, start_md, end_md)
                break
            except Exception as exc:  # noqa: BLE001
                log(f"{year} attempt {attempt} failed: {exc}")
                if attempt == 4:
                    failed.append(year)
                else:
                    time.sleep(15 * attempt)

    files = list(OUT.glob("*.nc"))
    total = sum(f.stat().st_size for f in files) / 1e6
    log(f"FINISHED in {(time.time() - t0) / 60:.1f} min | {len(files)} years, {total:.0f} MB")
    if failed:
        log(f"FAILED: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
