"""ERA5-Land daily rainfall for the Karnataka IMD cells — fallback truth if IMD Pune dies.

Same points, same range, same downstream path as the IMD grid; less accurate but always
available. Uses the 324 cells the weight matrix actually references, not the 551-cell bbox.

The archive API weights a call by locations x time range, so this chunks on both axes and
caches every chunk to disk. Resumable: a rerun skips what is already there.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "era5"
WEIGHTS = ROOT / "data" / "processed"
API = "https://archive-api.open-meteo.com/v1/archive"

# Only the monsoon season is ever used. May 1 covers the 30-day lookback from a June 1 onset,
# so full calendar years were ~3x wasted volume against a rate limit weighted by time range.
SEASON = ("05-01", "10-31")
YEARS = range(1991, 2025)
CHUNKS = [(f"{y}-{SEASON[0]}", f"{y}-{SEASON[1]}") for y in YEARS]

# 184 days instead of 1826 means a 50-cell batch sits well under the ~299 KB truncation ceiling.
BATCH = 50


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def cells():
    frames = [pd.read_parquet(p) for p in WEIGHTS.glob("weights_imd_*.parquet")]
    if not frames:
        raise SystemExit("no IMD weight matrices — run scripts/build_geo.py first")
    w = pd.concat(frames)
    c = w[["cell_id", "lat", "lon"]].drop_duplicates().sort_values("cell_id")
    return c.reset_index(drop=True)


def _is_hourly_cap(exc) -> bool:
    """Open-Meteo returns 429 both for burst throttling and for the hard hourly cap."""
    try:
        return "hourly" in exc.read().decode("utf-8", "ignore").lower()
    except Exception:  # noqa: BLE001
        return False


CAP_POLL = 300  # the cap may reset on a fixed hour or roll continuously — poll, don't guess


def fetch_adaptive(lats, lons, start, end):
    """Open-Meteo truncates large payloads at ~299 KB. Halve the batch and retry on that."""
    try:
        return fetch(lats, lons, start, end)
    except json.JSONDecodeError:
        if len(lats) == 1:
            raise
        mid = len(lats) // 2
        log(f"    truncated payload; splitting {len(lats)} -> {mid}+{len(lats) - mid}")
        left = fetch_adaptive(lats[:mid], lons[:mid], start, end)
        right = fetch_adaptive(lats[mid:], lons[mid:], start, end)
        as_list = lambda p: p if isinstance(p, list) else [p]  # noqa: E731
        return as_list(left) + as_list(right)


def fetch(lats, lons, start, end, tries=8):
    qs = urllib.parse.urlencode({
        "latitude": ",".join(f"{v:.4f}" for v in lats),
        "longitude": ",".join(f"{v:.4f}" for v in lons),
        "start_date": start,
        "end_date": end,
        "daily": "precipitation_sum",
        "timezone": "GMT",
    })
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(f"{API}?{qs}", timeout=240) as r:
                return json.loads(r.read())
        except json.JSONDecodeError:
            raise  # handled by fetch_adaptive, which halves the batch
        except Exception as exc:  # noqa: BLE001
            throttled = isinstance(exc, urllib.error.HTTPError) and exc.code == 429
            # DNS/connection blips need a longer pause than a plain retry
            netfail = isinstance(exc, urllib.error.URLError) and not isinstance(
                exc, urllib.error.HTTPError
            )
            if throttled and _is_hourly_cap(exc):
                # a hard hourly cap — seconds of backoff are pointless; poll until it frees
                log(f"    hourly API cap hit; re-checking in {CAP_POLL // 60} min")
                time.sleep(CAP_POLL)
                continue  # does not consume an attempt
            wait = 120 if throttled else (60 if netfail else 10 * attempt)
            log(f"    attempt {attempt} failed ({exc}); retry in {wait}s")
            if attempt == tries:
                raise
            time.sleep(wait)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=4.0, help="spacing between calls")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    grid = cells()
    total = len(CHUNKS) * ((len(grid) + BATCH - 1) // BATCH)
    log(f"{len(grid)} cells x {len(CHUNKS)} date chunks = {total} requests")

    t0, done, skipped = time.time(), 0, 0
    for start, end in CHUNKS:
        for b in range(0, len(grid), BATCH):
            chunk = grid.iloc[b : b + BATCH]
            tag = f"{start[:4]}_b{b // BATCH:03d}"
            dest = OUT / f"{tag}.json"
            if dest.exists() and dest.stat().st_size > 1000:
                skipped += 1
                continue

            payload = fetch_adaptive(list(chunk["lat"]), list(chunk["lon"]), start, end)
            items = payload if isinstance(payload, list) else [payload]
            dest.write_text(json.dumps({
                "cell_ids": list(chunk["cell_id"]),
                "start": start,
                "end": end,
                "data": items,
            }, separators=(",", ":")))
            done += 1
            if done % 20 == 0:
                log(f"  {done + skipped}/{total} chunks ({time.time() - t0:.0f}s elapsed)")
            time.sleep(args.sleep)

    size = sum(f.stat().st_size for f in OUT.glob("*.json")) / 1e6
    log(f"FINISHED in {(time.time() - t0) / 60:.1f} min | fetched={done} skipped={skipped} "
        f"| {size:.0f} MB, {len(list(OUT.glob('*.json')))} chunks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
