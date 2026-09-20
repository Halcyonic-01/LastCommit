"""Recent observed rainfall for the live run, in the same shape the training data used.

The model needs rain_1d..rain_30d and days_since_rain as of this morning. IMD's gridded
archive stops at 2024, so a live run pulls the last ~40 days from Open-Meteo instead and
hands them to the SAME feature builder the training set went through. Reusing that code
path is the point: a reimplementation is how live features quietly drift from trained ones.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "cache" / "obs"

API = "https://api.open-meteo.com/v1/forecast"
BATCH = 50          # locations per call; the API weights by locations x range
PAST_DAYS = 45      # 30-day features plus slack for the rolling warm-up
UA = {"User-Agent": "VarshaDrishti/0.1 (SIH 2026 PS 26086)"}


def _cell_lat_lon(cell_id: str) -> tuple[float, float]:
    _, lat, lon = cell_id.split(":")
    return float(lat), float(lon)


def _fetch(cells: list[str], past_days: int) -> dict[str, pd.Series]:
    lats, lons = zip(*(_cell_lat_lon(c) for c in cells))
    q = urllib.parse.urlencode({
        "latitude": ",".join(f"{v:.4f}" for v in lats),
        "longitude": ",".join(f"{v:.4f}" for v in lons),
        "daily": "precipitation_sum",
        "past_days": past_days,
        "forecast_days": 1,
        "timezone": "GMT",
    })
    req = urllib.request.Request(f"{API}?{q}", headers=UA)
    blob = json.loads(urllib.request.urlopen(req, timeout=120).read())
    items = blob if isinstance(blob, list) else [blob]
    out = {}
    for cell, item in zip(cells, items):
        d = item["daily"]
        out[cell] = pd.Series(d["precipitation_sum"], index=pd.to_datetime(d["time"]),
                              dtype="float64")
    return out


def fetch_recent(cells: list[str], as_of: str, past_days: int = PAST_DAYS,
                 use_cache: bool = True, log=print) -> pd.DataFrame:
    """-> DataFrame(date x cell_id) of observed daily mm. Cached per day, so a rerun of
    the nightly job (or an offline test) never re-hits the network."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{as_of}.json"
    if use_cache and path.exists():
        blob = json.loads(path.read_text())
        have = set(blob["cells"])
        short = [c for c in cells if c not in have]
        if short:
            # A cache written by a smaller request must not be served to a larger one.
            # Silently returning 50 of 324 cells sends the other 274 down the NWP-only
            # path and degrades the forecast with nothing in the logs to show for it.
            log(f"  cache holds {len(have)}/{len(cells)} cells — refetching")
        else:
            df = pd.DataFrame(blob["cells"])
            df.index = pd.to_datetime(blob["time"])
            return df[[c for c in cells if c in df.columns]]

    frames = {}
    for i in range(0, len(cells), BATCH):
        chunk = cells[i:i + BATCH]
        for attempt in range(4):
            try:
                frames.update(_fetch(chunk, past_days))
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 3:
                    raise
                log(f"  obs batch {i} attempt {attempt + 1} failed ({exc}); retrying")
                time.sleep(10 * (attempt + 1))
        log(f"  observations {min(i + BATCH, len(cells))}/{len(cells)}")

    df = pd.DataFrame(frames).sort_index()
    path.write_text(json.dumps({
        "fetched_at": pd.Timestamp.now("UTC").isoformat(),
        "as_of": as_of,
        "time": [d.strftime("%Y-%m-%d") for d in df.index],
        "cells": {c: df[c].tolist() for c in df.columns},
    }))
    return df


def from_imd(rain: pd.DataFrame, as_of: str, past_days: int = PAST_DAYS) -> pd.DataFrame:
    """Offline equivalent: the same window taken from the IMD archive, for replay and tests."""
    end = pd.Timestamp(as_of)
    return rain.loc[end - pd.Timedelta(days=past_days):end]
