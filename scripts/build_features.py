"""Build the P5 training table: per cell, per day, Jun-Sep, 1991-2024."""

import argparse
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

from varshadrishti.data.rainfall import load_imd  # noqa: E402
from varshadrishti.features import build as B  # noqa: E402

OUT = ROOT / "data" / "processed"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1991)
    ap.add_argument("--end", type=int, default=2024)
    ap.add_argument("--source", default="imd")
    a = ap.parse_args()
    years = range(a.start, a.end + 1)

    # only the cells the area-weight matrices actually reference
    w = pd.read_parquet(OUT / f"weights_{a.source}_hoblis.parquet")
    cells = sorted(set(w.cell_id))

    # Subset at read time: the full India grid is 4,964 cells and we keep 323 of them.
    pad = 0.3
    bounds = (w.lon.min() - pad, w.lat.min() - pad, w.lon.max() + pad, w.lat.max() + pad)
    log(f"loading {a.source} {a.start}-{a.end} over {bounds}")
    rain = load_imd(a.start, a.end, bounds=bounds)
    have = [c for c in cells if c in rain.columns]
    log(f"{len(have)}/{len(cells)} weight cells present (sea-masked cells are dropped)")
    rain = rain[have]

    log("building")
    df, onset = B.build(rain, years, progress=log)

    f = OUT / "features.parquet"
    o = OUT / "onset_labels.parquet"
    df.to_parquet(f, index=False, compression="zstd")
    onset.to_parquet(o, index=False, compression="zstd")
    log(f"{f.name}  {len(df):,} rows x {df.shape[1]} cols  {f.stat().st_size/1e6:.0f} MB")
    log(f"{o.name}  {len(onset):,} rows  {o.stat().st_size/1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
