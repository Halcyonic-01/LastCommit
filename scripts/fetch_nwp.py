"""Fetch and cache NWP ensembles for every IMD cell covering Karnataka.

Two models, two APIs:
  ec46  ECMWF EC46 via the Seasonal API  - 46 days, 50 members + control (primary)
  gefs  GEFS via the Ensemble API        - 35 days, 30 members (model diversity)

Cached to data/cache/<model>/<date>.json and committed, so a demo survives an
Open-Meteo outage and the pipeline can be developed offline.
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
WEIGHTS = ROOT / "data" / "processed"

MODELS = {
    "ec46": {
        "api": "https://seasonal-api.open-meteo.com/v1/seasonal",
        "days": 46,
        "params": {},
        "label": "ECMWF EC46 via Open-Meteo Seasonal API",
    },
    "gefs": {
        "api": "https://ensemble-api.open-meteo.com/v1/ensemble",
        "days": 35,
        "params": {"models": "gfs_seamless"},
        "label": "GEFS 35-day via Open-Meteo Ensemble API",
    },
}
BATCH = 50


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def imd_cells():
    """Distinct IMD cells referenced by any Karnataka area weight."""
    frames = [pd.read_parquet(p) for p in WEIGHTS.glob("weights_imd_*.parquet")]
    if not frames:
        raise SystemExit("no IMD weight matrices — run scripts/build_geo.py first")
    w = pd.concat(frames)
    return w[["cell_id", "lat", "lon"]].drop_duplicates().sort_values("cell_id").reset_index(drop=True)


def fetch(spec, lats, lons, tries=3):
    qs = urllib.parse.urlencode({
        "latitude": ",".join(f"{v:.4f}" for v in lats),
        "longitude": ",".join(f"{v:.4f}" for v in lons),
        "daily": "precipitation_sum",
        "forecast_days": spec["days"],
        **spec["params"],
    })
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(f"{spec['api']}?{qs}", timeout=180) as r:
                return json.loads(r.read())
        except Exception as exc:  # noqa: BLE001
            log(f"    attempt {attempt} failed: {exc}")
            if attempt == tries:
                raise
            time.sleep(10 * attempt)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=sorted(MODELS), default="ec46")
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()

    spec = MODELS[args.model]
    out_dir = CACHE / args.model
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{args.date}.json"
    if dest.exists() and dest.stat().st_size > 10_000:
        log(f"{args.model}/{dest.name} already cached, skipping")
        return 0

    cells = imd_cells()
    log(f"{args.model}: {len(cells)} IMD cells over Karnataka")

    members_seen, out, t0 = 0, {}, time.time()
    for b in range(0, len(cells), BATCH):
        chunk = cells.iloc[b : b + BATCH]
        payload = fetch(spec, list(chunk["lat"]), list(chunk["lon"]))
        items = payload if isinstance(payload, list) else [payload]
        for cell_id, item in zip(chunk["cell_id"], items):
            daily = item["daily"]
            members = [k for k in daily if k.startswith("precipitation_sum_member")]
            members_seen = max(members_seen, len(members))
            out[cell_id] = {
                "time": daily["time"],
                "control": daily["precipitation_sum"],
                "members": [daily[m] for m in members],
            }
        log(f"  {b + len(chunk):4d}/{len(cells)} cells")
        time.sleep(1)

    blob = {
        "model": args.model,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": spec["label"],
        "forecast_days": spec["days"],
        "members": members_seen,
        "cells": out,
    }
    dest.write_text(json.dumps(blob, separators=(",", ":")), encoding="utf-8")
    log(
        f"cached {len(out)} cells x {members_seen} members -> {args.model}/{dest.name} "
        f"({dest.stat().st_size / 1e6:.1f} MB, {time.time() - t0:.0f}s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
