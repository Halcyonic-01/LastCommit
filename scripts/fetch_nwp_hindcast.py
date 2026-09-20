"""Past NWP forecasts at fixed 1-7 day leads, so the short-lead blend weight stops being a prior.

Open-Meteo serves no EC46 hindcast and the seasonal endpoint keeps only ~4 weeks, so the
long leads cannot be verified without a Copernicus/ECMWF account. The Previous Runs API
DOES archive fixed lead offsets 1-7 days from January 2024, which overlaps the 2024
monsoon we hold IMD observations for. That settles week 1 on evidence and nothing further,
which is exactly how it is reported.
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

API = "https://previous-runs-api.open-meteo.com/v1/forecast"
OUT = ROOT / "data" / "raw" / "nwp_hindcast"
BATCH = 12          # hourly x 4 months is heavy; the API weights locations x range
LEADS = (1, 3, 7)
UA = {"User-Agent": "VarshaDrishti/0.1 (SIH 2026 PS 26086)"}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def fetch(cells, start, end, leads):
    lats, lons = zip(*((float(c.split(":")[1]), float(c.split(":")[2])) for c in cells))
    q = urllib.parse.urlencode({
        "latitude": ",".join(f"{v:.4f}" for v in lats),
        "longitude": ",".join(f"{v:.4f}" for v in lons),
        "hourly": ",".join(f"precipitation_previous_day{d}" for d in leads),
        "start_date": start, "end_date": end, "timezone": "GMT",
    })
    req = urllib.request.Request(f"{API}?{q}", headers=UA)
    blob = json.loads(urllib.request.urlopen(req, timeout=180).read())
    items = blob if isinstance(blob, list) else [blob]

    out = {}
    for cell, item in zip(cells, items):
        h = item["hourly"]
        idx = pd.to_datetime(h["time"])
        # hourly -> daily totals, per lead
        out[cell] = {d: pd.Series(h[f"precipitation_previous_day{d}"], index=idx)
                       .resample("D").sum() for d in leads}
    return out


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--year", type=int, default=2024)
    a.add_argument("--start-md", default="05-25")   # slack for the 7-day lead warm-up
    a.add_argument("--end-md", default="10-07")
    args = a.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{args.year}.parquet"
    if dest.exists():
        log(f"{dest.name} already present")
        return 0

    w = pd.read_parquet(ROOT / "data" / "processed" / "weights_imd_hoblis.parquet")
    cells = sorted(set(w.cell_id))
    start, end = f"{args.year}-{args.start_md}", f"{args.year}-{args.end_md}"
    log(f"{len(cells)} cells, {start}..{end}, leads {LEADS}")

    rows = []
    for i in range(0, len(cells), BATCH):
        chunk = cells[i:i + BATCH]
        for attempt in range(4):
            try:
                got = fetch(chunk, start, end, LEADS)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 3:
                    raise
                log(f"  batch {i} attempt {attempt + 1}: {exc}")
                time.sleep(15 * (attempt + 1))
        for cell, per_lead in got.items():
            for d, s in per_lead.items():
                rows.append(pd.DataFrame({"cell_id": cell, "lead": d,
                                          "date": s.index, "mm": s.to_numpy()}))
        log(f"  {min(i + BATCH, len(cells))}/{len(cells)} cells")

    df = pd.concat(rows, ignore_index=True)
    df.to_parquet(dest, index=False, compression="zstd")
    log(f"{dest.name}: {len(df):,} rows, {dest.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
