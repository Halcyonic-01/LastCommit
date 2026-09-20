"""How fast does NWP skill decay with lead? The evidence behind the blend weight's SHAPE.

Scope, stated up front: fixed lead offsets 1-7 days, one monsoon (2024), verified against
IMD. It cannot settle weeks 2-4 — no EC46 hindcast is obtainable without a Copernicus or
ECMWF account. What it CAN settle is whether a dynamical model really is worth 0.70 of the
week-1 blend, and how steeply its advantage falls away inside the first week.

Target: is a given day dry (<2.5 mm)? Common to NWP, climatology and observations, so the
three are comparable without inventing a shared probability.
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

from varshadrishti.data.rainfall import load_imd  # noqa: E402
from varshadrishti.features import labels as L  # noqa: E402
from varshadrishti.model import metrics as M  # noqa: E402

RAW = ROOT / "data" / "raw" / "nwp_hindcast"
PROC = ROOT / "data" / "processed"
YEAR = 2024


def main():
    f = RAW / f"{YEAR}.parquet"
    if not f.exists():
        print(f"no hindcast for {YEAR} — run scripts/fetch_nwp_hindcast.py")
        return 1
    fc = pd.read_parquet(f)
    fc["date"] = pd.to_datetime(fc["date"])

    w = pd.read_parquet(PROC / "weights_imd_hoblis.parquet")
    pad = 0.3
    b = (w.lon.min() - pad, w.lat.min() - pad, w.lon.max() + pad, w.lat.max() + pad)
    rain = load_imd(YEAR, YEAR, bounds=b)
    rain = rain[[c for c in sorted(set(w.cell_id)) if c in rain.columns]]

    obs = (rain.stack().rename("obs_mm").reset_index()
              .rename(columns={"time": "date", "level_1": "cell_id"}))
    obs["date"] = pd.to_datetime(obs["date"])
    obs["dry"] = (obs["obs_mm"] < L.RAINY_DAY_MM).astype(float)

    tab = pd.read_parquet(PROC / "inference_tables.parquet")
    start = pd.Timestamp(YEAR, *L.SEASON_START_MD)
    obs["sday"] = (obs["date"] - start).dt.days
    obs = obs.merge(tab[["cell_id", "sday", "clim_dryday_doy"]], on=["cell_id", "sday"],
                    how="inner")

    d = fc.merge(obs, on=["cell_id", "date"], how="inner")
    d = d[(d.date >= start) & (d.date <= pd.Timestamp(YEAR, 9, 30))]
    print(f"{len(d):,} (forecast, observation) pairs over {d.cell_id.nunique()} cells, "
          f"{d.date.nunique()} days\n")

    y = d["dry"].to_numpy()
    clim = d["clim_dryday_doy"].to_numpy()
    print(f"observed dry-day rate {y.mean():.3f} | climatology Brier "
          f"{M.brier(y, clim):.4f}\n")
    print(f"{'lead':>5}  {'n':>8}  {'NWP Brier':>10}  {'BSS vs clim':>12}  {'AUC':>6}  "
          f"{'best w on NWP':>14}")

    out = {}
    for lead, g in d.groupby("lead"):
        yy = g["dry"].to_numpy()
        cc = g["clim_dryday_doy"].to_numpy()
        # deterministic mm -> probability, by the observed dry rate in each forecast bin
        # reset_index matters: qcut keeps g's original index while yy is 0..n, and a
        # groupby across mismatched indexes silently yields all-NaN
        bins = pd.qcut(g["mm"].reset_index(drop=True), 10, labels=False, duplicates="drop")
        p = pd.Series(yy).groupby(bins).transform("mean").to_numpy()
        assert not np.isnan(p).any(), "binned probabilities contain NaN"

        grid = np.linspace(0, 1, 51)
        bs = [M.brier(yy, wv * p + (1 - wv) * cc) for wv in grid]
        best = float(grid[int(np.argmin(bs))])
        out[int(lead)] = {"n": int(len(g)), "brier": M.brier(yy, p),
                          "bss_vs_clim": M.bss(yy, p, cc), "auc": M.roc_auc(yy, p),
                          "best_nwp_weight": best}
        print(f"{lead:>5}  {len(g):>8,}  {out[int(lead)]['brier']:>10.4f}  "
              f"{out[int(lead)]['bss_vs_clim']:>+12.4f}  {out[int(lead)]['auc']:>6.3f}  "
              f"{best:>14.2f}")

    (ROOT / "logs" / "nwp_shortlead.json").write_text(json.dumps(out, indent=1))
    print("\nNOTE: leads 1-7 only, one season, in-sample binning — an indication of the")
    print("weight's SHAPE at short lead, not a calibrated weight. Weeks 2-4 remain a prior.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
