"""Backtest the shipped model over a real season: what would it have said, and was it right?

2025 has no IMD ground truth yet -- the archive stops at 2024 (checked before writing this;
see IMPLEMENTATION_PLAN.md P7). This replays 2024 instead: the model's own chronological
TEST year, already scored in models/metrics.json, never seen in training. That makes this
replay and the /verify skill numbers the same evidence, not two disconnected claims.

Reuses exactly the scoring path scripts/score_xgb.py used to produce those numbers --
EX.attach() for train-only climatology + extended features, PX.predict_all() for the
real boosters -- rather than re-running the full per-area contract/rules pipeline 92
times, which would write ~100k redundant JSON files for no benefit: a hindcast is a bulk
backtest, not 92 separate live nights.

Output: one long-form parquet (date x area x event x lead, predicted vs actual, at both
block and district level) for real analysis -- e.g. finding a genuine false-onset story --
plus a compact district-level JSON for the frontend replay scrubber.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti.features import extended as EX  # noqa: E402
from varshadrishti.model import predict_xgb as PX  # noqa: E402
from varshadrishti.pipeline import aggregate as A  # noqa: E402

PROC = ROOT / "data" / "processed"
EVENTS = ("onset", "false_onset", "dry7", "dry14", "heavy")
LEADS = (7, 14, 21, 28)
LEAD_KEY = {7: "w1", 14: "w2", 21: "w3", 28: "w4"}


def log(m: str) -> None:
    print(m, flush=True)


def compute_cell_level(start: str, end: str) -> pd.DataFrame:
    """Predicted probability + real outcome, one row per cell-day, wide by target."""
    log(f"loading features.parquet, {start} -> {end}")
    df = pd.read_parquet(PROC / "features.parquet")
    df = df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)
    log(f"  {len(df):,} cell-days, {df['cell_id'].nunique()} cells, {df['date'].nunique()} dates")

    log("attaching extended features (train-only climatology, matching the shipped model)")
    df = EX.attach(df, ecmwf=True, clean_climatology=True)

    log("scoring with the shipped XGBoost boosters")
    pred = PX.predict_all(df)
    pred.columns = [f"{c}_pred" for c in pred.columns]

    actual = df[[f"y_{e}_{h}" for e in EVENTS for h in LEADS]].rename(
        columns={c: f"{c}_actual" for c in df.columns if c.startswith("y_")})
    return pd.concat([df[["date", "cell_id"]], pred, actual], axis=1)


def aggregate_level(cell_level: pd.DataFrame, layer: str) -> pd.DataFrame:
    """Area-weighted mean of every predicted/actual column, one date at a time."""
    cols = [c for c in cell_level.columns if c not in ("date", "cell_id")]
    out = []
    for d, day in cell_level.groupby("date"):
        vals = day.set_index("cell_id")[cols]
        agg = A.to_areas(vals, layer, clip=(0.0, 1.0))
        agg.insert(0, "date", d)
        out.append(agg.reset_index())
    return pd.concat(out, ignore_index=True)


def to_long(area_level: pd.DataFrame, level_name: str) -> pd.DataFrame:
    """Wide (one column per event/lead/kind) -> long (one row per event+lead+kind)."""
    rows = []
    for e in EVENTS:
        for h in LEADS:
            for kind in ("pred", "actual"):
                col = f"y_{e}_{h}_{kind}"
                if col not in area_level.columns:
                    continue
                sub = area_level[["date", "area_id", col]].rename(columns={col: "value"})
                sub["event"], sub["lead"], sub["kind"], sub["level"] = e, LEAD_KEY[h], kind, level_name
                rows.append(sub)
    return pd.concat(rows, ignore_index=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default="2024-08-31")
    ap.add_argument("--out", default=str(PROC / "hindcast_2024.parquet"))
    ap.add_argument("--web-out", default=str(ROOT / "forecast" / "hindcast" / "2024.json"))
    a = ap.parse_args()

    cell_level = compute_cell_level(a.start, a.end)

    log("aggregating to block and district level")
    long_frames = []
    for layer in ("block", "district"):
        area_level = aggregate_level(cell_level, layer)
        long_frames.append(to_long(area_level, layer))
        log(f"  {layer}: {area_level['area_id'].nunique()} areas")
    long_df = pd.concat(long_frames, ignore_index=True)
    long_df.to_parquet(a.out, index=False)
    log(f"wrote {a.out} ({len(long_df):,} rows)")

    log("building the compact district-level scrubber payload")
    district = long_df[long_df["level"] == "district"]
    wide = district.pivot_table(index=["date", "area_id", "event", "lead"],
                                columns="kind", values="value").reset_index()
    payload = {}
    for aid, g in wide.groupby("area_id"):
        payload[aid] = {}
        for d, gd in g.groupby(g["date"].astype(str)):
            payload[aid][d] = {
                f"{r.event}_{r.lead}": {"pred": round(float(r.pred), 4),
                                        "actual": round(float(r.actual), 4)}
                for r in gd.itertuples()
            }
    Path(a.web_out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.web_out).write_text(json.dumps(
        {"start": a.start, "end": a.end, "level": "district", "areas": payload}, default=str))
    log(f"wrote {a.web_out} ({Path(a.web_out).stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
