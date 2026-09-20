"""Freeze everything the nightly job needs that would otherwise require the IMD archive.

A GitHub runner has the repo, not 825 MB of .grd files. Climatology and the per-cell onset
bar are derived from that archive but are tiny once computed, so they are exported here and
committed. The nightly job then needs only: this table, the models, the weight matrices,
and whatever it fetches from the network.
"""

import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

from varshadrishti.data.rainfall import load_imd  # noqa: E402
from varshadrishti.features.climatology import CLIM_COLS, FoldClimatology  # noqa: E402

PROC = ROOT / "data" / "processed"
OUT = PROC / "inference_tables.parquet"


def main():
    feat = pd.read_parquet(PROC / "features.parquet",
                           columns=["cell_id", "sday", "doy", "onset_threshold_mm"])
    onset = pd.read_parquet(PROC / "onset_labels.parquet")
    w = pd.read_parquet(PROC / "weights_imd_hoblis.parquet")
    cells = sorted(set(w.cell_id))
    years = sorted(onset.year.unique())

    pad = 0.3
    b = (w.lon.min() - pad, w.lat.min() - pad, w.lon.max() + pad, w.lat.max() + pad)
    rain = load_imd(min(years), max(years), bounds=b)
    rain = rain[[c for c in cells if c in rain.columns]]

    rows = feat[["cell_id", "sday", "doy"]]
    fc = FoldClimatology(rain, years, onset, rows)
    clim = fc.for_inference()
    clim["cell_id"] = rows["cell_id"].to_numpy()
    clim["sday"] = rows["sday"].to_numpy()

    # one row per (cell, season day) — onset_doy_anom is derived at run time from doy
    tab = (clim.drop(columns=["onset_doy_anom"])
                .drop_duplicates(["cell_id", "sday"])
                .merge(feat.groupby("cell_id")["onset_threshold_mm"].first().rename("onset_threshold_mm"),
                       on="cell_id", how="left"))
    tab.to_parquet(OUT, index=False, compression="zstd")
    print(f"{OUT.name}: {len(tab):,} rows x {tab.shape[1]} cols, "
          f"{OUT.stat().st_size / 1e6:.2f} MB  ({tab.cell_id.nunique()} cells x "
          f"{tab.sday.nunique()} season days)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
