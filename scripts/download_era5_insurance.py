"""P0 insurance: ERA5-Land daily rainfall for the Karnataka IMD grid cells.

Fallback truth data if the IMD Pune download stalls or dies. Same points,
same date range, same downstream code path as the IMD grid - less accurate,
but instantly available.

The archive API times out on a 34-year single request, so this chunks on
BOTH axes: 5-year date blocks x batches of locations. Every chunk is cached
to disk and skipped on re-run, so the job is resumable and can be left
running while IMD downloads in parallel.

Grid: IMD 0.25 deg cells inside the Karnataka bbox (lat 11.5-18.5, lon 74.0-78.6)
      = 29 x 19 = 551 cells (~300 are land; the sea cells are dropped at P2
      when real boundaries arrive).
Cost: ~127 MB raw JSON, ~20-40 min.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "openmeteo" / "era5"

LAT0, LAT1 = 11.5, 18.5
LON0, LON1 = 74.0, 78.6
STEP = 0.25

CHUNKS = [
    ("1991-01-01", "1995-12-31"),
    ("1996-01-01", "2000-12-31"),
    ("2001-01-01", "2005-12-31"),
    ("2006-01-01", "2010-12-31"),
    ("2011-01-01", "2015-12-31"),
    ("2016-01-01", "2020-12-31"),
    ("2021-01-01", "2024-12-31"),
]
# Open-Meteo's free tier weights a call by locations x time range, not by
# request count. 25 locations x 5 years tripped HTTP 429 within a minute.
BATCH = 10
API = "https://archive-api.open-meteo.com/v1/archive"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def grid():
    n_lat = int(round((LAT1 - LAT0) / STEP)) + 1
    n_lon = int(round((LON1 - LON0) / STEP)) + 1
    return [
        (round(LAT0 + STEP * i, 2), round(LON0 + STEP * j, 2))
        for i in range(n_lat)
        for j in range(n_lon)
    ]


def fetch(lats, lons, start, end, tries=4):
    url = (
        f"{API}?latitude={','.join(map(str, lats))}"
        f"&longitude={','.join(map(str, lons))}"
        f"&start_date={start}&end_date={end}"
        f"&daily=precipitation_sum&timezone=GMT"
    )
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return json.loads(r.read())
        except Exception as exc:  # noqa: BLE001
            throttled = isinstance(exc, urllib.error.HTTPError) and exc.code == 429
            wait = 300 if throttled else 10 * attempt
            log(f"    attempt {attempt} failed ({exc}); retry in {wait}s")
            if attempt == tries:
                raise
            time.sleep(wait)
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cells = grid()
    log(f"{len(cells)} grid cells x {len(CHUNKS)} date chunks")
    t0 = time.time()
    done = skipped = 0

    for start, end in CHUNKS:
        for b in range(0, len(cells), BATCH):
            batch = cells[b : b + BATCH]
            tag = f"{start[:4]}_{end[:4]}_b{b // BATCH:03d}"
            dest = OUT / f"{tag}.json"
            if dest.exists() and dest.stat().st_size > 1000:
                skipped += 1
                continue
            lats = [c[0] for c in batch]
            lons = [c[1] for c in batch]
            t = time.time()
            payload = fetch(lats, lons, start, end)
            dest.write_text(json.dumps(payload))
            done += 1
            log(
                f"  {tag}: {len(batch)} pts, {dest.stat().st_size / 1024:.0f} KB, "
                f"{time.time() - t:.1f}s"
            )
            time.sleep(6)  # stay under the free tier's weighted rate limit

    total = sum(f.stat().st_size for f in OUT.glob("*.json")) / 1e6
    log(
        f"FINISHED in {(time.time() - t0) / 60:.1f} min | "
        f"fetched={done} skipped={skipped} | {total:.0f} MB on disk"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
