"""GEFSv12 reforecast (NOAA, AWS Open Data) — a REAL long-lead hindcast for W2.

This is the dataset that closes the 7-28 day gap. It is public, unauthenticated, and
covers 2000-2019, which overlaps our IMD observations completely. Once weekly an 11-member
reforecast runs out to +35 days, so leads 10-28 — w2, w3 and w4, exactly the leads we
could not verify — are directly measurable.

Ruled out first, and why: Open-Meteo Previous Runs stops at 7 days; its seasonal endpoint
keeps ~4 weeks and returns nulls for older windows; ECMWF S2S and the new ECDS both
require a login. GEFS is a different model from EC46, which is stated in the provenance —
but it is a real dynamical ensemble verified against real observations, not an assumption.

Downloads ~10 MB per member per init, subsets Karnataka, keeps daily totals, discards the
GRIB. Resumable: a rerun skips inits already on disk.
"""

import argparse
import concurrent.futures as cf
import sys
import tempfile
import time
import urllib.request
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

BASE = "https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast"
OUT = ROOT / "data" / "raw" / "gefs_reforecast_full"
MEMBERS = ["c00"] + [f"p{i:02d}" for i in range(1, 11)]
KA = dict(lat=(11.0, 19.0), lon=(74.0, 79.0))   # Karnataka plus a margin
# 8 concurrent threads produced 967 DNS failures in one run — the local resolver, not
# S3, was the bottleneck (S3 answers fine when probed serially). Fewer workers with
# patient retries finishes sooner than fast requests that mostly fail.
WORKERS = 3


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def extended_inits(year: int, months=(6, 7, 8, 9), every: int = 2) -> list[str]:
    """Extended 35-day runs are weekly (Wednesdays). `every`=2 takes every other one."""
    days = pd.date_range(f"{year}-{min(months):02d}-01", f"{year}-{max(months):02d}-30", freq="W-WED")
    return [d.strftime("%Y%m%d00") for d in days[::every]]


def fetch_member(init: str, member: str) -> pd.DataFrame | None:
    """-> daily Karnataka rainfall for one member, indexed by valid date."""
    import xarray as xr

    # BOTH windows. Days:10-35 alone cannot see leads 1-9, so "the FIRST dry spell starts
    # in week k" — which is what P_stat computes, as a difference of nested cumulative
    # targets — is structurally unmeasurable from it. Without days 1-9 you cannot know
    # whether an earlier spell already happened.
    frames = []
    for part in ("Days:1-10", "Days:10-35"):
        url = f"{BASE}/{init[:4]}/{init}/{member}/{part}/apcp_sfc_{init}_{member}.grib2"
        got = None
        for attempt in range(6):        # DNS drops arrive in bursts lasting minutes
            got = _one_window(url, member)
            if got is not None:
                break
            time.sleep(min(60, 8 * (attempt + 1)))
        if got is not None:
            frames.append(got)
    if len(frames) < 2:
        return None      # both windows required, or leads 1-9 are missing and
                         # "first occurrence" cannot be evaluated at all
    out = pd.concat(frames).groupby(["valid", "latitude", "longitude"], as_index=False).max()
    return out


def _one_window(url: str, member: str):
    """One GRIB window -> tidy daily frame on the COARSE 0.5-degree grid.

    Two traps here, both silent:
      - Days:1-10 holds TWO datasets, a single-field `cf` and the real 79-step `pf`
        series. xr.open_dataset picks the first, which has no `step` dimension, so ten
        of eleven members came back empty with only a warning to show for it.
      - Days:1-10 is 0.25 degrees and Days:10-35 is 0.5. Concatenating them without
        regridding yields two disjoint sets of coordinates, not a merged series.
    """
    import cfgrib

    try:
        with tempfile.NamedTemporaryFile(suffix=".grib2", delete=True) as tmp:
            with urllib.request.urlopen(url, timeout=300) as r:
                tmp.write(r.read())
            tmp.flush()
            # take the dataset that actually carries a forecast series
            cands = [d for d in cfgrib.open_datasets(tmp.name, backend_kwargs={"indexpath": ""})
                     if "step" in d.sizes and "tp" in d.data_vars]
            if not cands:
                return None
            ds = max(cands, key=lambda d: d.sizes["step"])
            sub = ds.sel(latitude=slice(KA["lat"][1], KA["lat"][0]),
                         longitude=slice(*KA["lon"]))
            # snap a fine grid onto the coarse one so both windows share coordinates
            sub = sub.sel(latitude=[v for v in sub.latitude.values if float(v) % 0.5 == 0],
                          longitude=[v for v in sub.longitude.values if float(v) % 0.5 == 0])
            # Keep the GRID, never an area mean. The blend works per cell, so collapsing
            # 187 grid points to one number would leave far too few samples to estimate
            # a weight — and would hide all the spatial structure the weight depends on.
            tp = sub["tp"]
            valid = pd.to_datetime(sub.time.values) + pd.to_timedelta(sub.step.values)
            da = tp.assign_coords(step=("step", valid)).rename({"step": "valid"})
            daily = da.resample(valid="1D").sum()      # 6-hourly accumulations -> daily
            out = (daily.to_dataframe(name=member).reset_index()
                        [["valid", "latitude", "longitude", member]])
            ds.close()
            return out
    except Exception as exc:  # noqa: BLE001
        log(f"    {url.rsplit('/', 3)[-3]} {member}: {type(exc).__name__} {exc}")
        return None


def fetch_init(init: str) -> pd.DataFrame | None:
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        got = list(ex.map(lambda m: fetch_member(init, m), MEMBERS))
    ok = [g for g in got if g is not None]
    if len(ok) < 6:
        log(f"  {init}: only {len(ok)}/11 members — skipping")
        return None
    df = ok[0]
    for g in ok[1:]:
        df = df.merge(g, on=["valid", "latitude", "longitude"], how="outer")
    df["init"] = pd.Timestamp(init[:8])
    df["lead"] = (df["valid"] - df["init"]).dt.days
    return df


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--start-year", type=int, default=2010)
    a.add_argument("--end-year", type=int, default=2019)
    a.add_argument("--every", type=int, default=2, help="take every Nth weekly init")
    args = a.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    inits = [i for y in range(args.start_year, args.end_year + 1)
             for i in extended_inits(y, every=args.every)]
    todo = [i for i in inits if not (OUT / f"{i}.parquet").exists()]
    log(f"{len(inits)} extended inits, {len(todo)} to fetch "
        f"(~{len(todo) * 11 * 10.3 / 1024:.1f} GB)")

    t0 = time.time()
    for n, init in enumerate(todo, 1):
        df = fetch_init(init)
        if df is not None:
            df.to_parquet(OUT / f"{init}.parquet", index=False, compression="zstd")
        done = len(list(OUT.glob("*.parquet")))
        rate = (time.time() - t0) / n
        log(f"  {init}  [{done}/{len(inits)}]  {rate:.0f}s/init  "
            f"eta {rate * (len(todo) - n) / 60:.0f} min")
    log(f"DONE {len(list(OUT.glob('*.parquet')))} inits in {(time.time()-t0)/60:.0f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
