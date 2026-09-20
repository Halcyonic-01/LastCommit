"""Derive the blend weight per lead from a REAL long-lead hindcast (W2).

GEFSv12 reforecast, 11 members to +35 days, 2010-2019 monsoons, verified against IMD.
For every (init, cell, lead window) this builds the three things a weight needs:

    P_nwp   member fraction for the event, from the reforecast ensemble
    P_stat  our model's out-of-fold prediction for that same date and cell
    y       what actually happened, from IMD

and solves for the weight minimising Brier. Validation is leave-one-YEAR-out over the 10
reforecast seasons: the weight is fitted on nine and scored on the tenth, so the number
reported was never fitted on the season it grades.

Honest boundaries, both carried into the provenance:
  - GEFS is not EC46. A different model, so this is a measured proxy for our ensemble's
    weight, not a direct measurement of it. It is still a real dynamical ensemble scored
    against real observations at the real leads, which the extrapolation was not.
  - Days:10-35 starts at lead 10, so w2 is measured over days 10-14, not the full 8-14.
"""

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

from varshadrishti.features import labels as L  # noqa: E402
from varshadrishti.model import metrics as M  # noqa: E402

RAW = ROOT / "data" / "raw" / "gefs_reforecast_full"
PROC = ROOT / "data" / "processed"
MEMBERS = ["c00"] + [f"p{i:02d}" for i in range(1, 11)]
# GEFS extended data starts at lead 10, so w2 is days 10-14 rather than the full 8-14
WINDOWS = {"w1": (1, 7), "w2": (8, 14), "w3": (15, 21), "w4": (22, 28)}
# Windowed, to match the windowed P_nwp and the windowed outcome: the cumulative
# targets are nested, so P(in week k) = P(within k) - P(within k-1), exactly.
TARGET = {"w1": ("y_dry7_7", None),
          "w2": ("y_dry7_14", "y_dry7_7"),
          "w3": ("y_dry7_21", "y_dry7_14"),
          "w4": ("y_dry7_28", "y_dry7_21")}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def nearest_cell(lat, lon, cells: pd.DataFrame) -> pd.Series:
    """Map each 0.5-degree GEFS point to the closest 0.25-degree IMD cell."""
    la = cells["lat"].to_numpy()[None, :]
    lo = cells["lon"].to_numpy()[None, :]
    d = (lat.to_numpy()[:, None] - la) ** 2 + (lon.to_numpy()[:, None] - lo) ** 2
    return cells["cell_id"].to_numpy()[d.argmin(axis=1)]


def _starts_in(dry: pd.Series, lo: int, hi: int) -> bool:
    for start in range(lo, hi + 1):
        run = dry.reindex(range(start, start + 7))
        if run.notna().all() and run.sum() == 7:
            return True
    return False


def member_dry_fraction(g: pd.DataFrame, lo: int, hi: int) -> float:
    """Fraction of members where the FIRST 7-day dry run starts inside [lo, hi].

    First, not any. P_stat is a difference of nested cumulative targets, which is
    "the first spell starts in week k". Those events are not disjoint — measured over
    2010-2015, days 1-7 = 0.363 and days 8-14 = 0.389 but days 1-14 = 0.536, so
    P(both) = 0.216. Scoring "any occurrence" against a first-occurrence P_stat
    compares two different events, which is what made the weights swing 0.58 -> 1.00.

    This needs leads 1..lo-1 to be visible, which is why the fetcher pulls Days:1-10
    as well as Days:10-35.
    """
    cols = [c for c in MEMBERS if c in g.columns]
    hits = 0
    for m in cols:
        dry = (g.set_index("lead")[m].sort_index() < L.RAINY_DAY_MM).astype(int)
        if _starts_in(dry, lo, hi) and not (lo > 1 and _starts_in(dry, 1, lo - 1)):
            hits += 1
    return (hits + 0.5) / (len(cols) + 1.0)       # never 0 or 1 — see pipeline/nwp.py


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--out", default=str(ROOT / "logs" / "blend_weights_measured.json"))
    args = a.parse_args()

    files = sorted(RAW.glob("*.parquet"))
    if len(files) < 20:
        print(f"only {len(files)} reforecast inits — run scripts/fetch_gefs_reforecast.py")
        return 1
    log(f"{len(files)} reforecast initialisations")

    w = pd.read_parquet(PROC / "weights_imd_hoblis.parquet")
    cells = w[["cell_id", "lat", "lon"]].drop_duplicates("cell_id").reset_index(drop=True)
    oof = pd.read_parquet(PROC / "oof_predictions.parquet")
    oof["date"] = pd.to_datetime(oof["date"])

    from varshadrishti.data.rainfall import load_imd
    pad = 0.3
    b = (w.lon.min() - pad, w.lat.min() - pad, w.lon.max() + pad, w.lat.max() + pad)
    years = sorted({int(f.stem[:4]) for f in files})
    rain = load_imd(min(years), max(years), bounds=b)
    rain = rain[[c for c in cells.cell_id if c in rain.columns]]
    log(f"IMD truth {rain.index.min().date()} .. {rain.index.max().date()}")

    # observed: does a 7-day dry run start in [init+lo, init+hi]?
    dry = rain < L.RAINY_DAY_MM
    run7 = dry.rolling(7, min_periods=7).sum().shift(-6) >= 7   # starts on this day

    rows = []
    for f in files:
        df = pd.read_parquet(f)
        df["cell_id"] = nearest_cell(df["latitude"], df["longitude"], cells)
        # GEFS is 0.5 deg and IMD is 0.25, so several grid points land on one cell.
        # Collapse them first — otherwise a cell has duplicate `lead` values and the
        # per-member reindex below cannot align.
        mem = [c for c in MEMBERS if c in df.columns]
        df = df.groupby(["cell_id", "lead"], as_index=False)[mem].mean()
        init = pd.Timestamp(f.stem[:8])
        for lead, (lo, hi) in WINDOWS.items():
            sub = df[(df.lead >= lo) & (df.lead <= hi + 7)]
            if sub.empty:
                continue
            p_nwp = (sub.groupby("cell_id", group_keys=False)
                        .apply(lambda g: member_dry_fraction(g, lo, hi)))
            # Stay inside the monsoon. Past 30 Sep a 7-day dry run is near-certain, so a
            # window spilling into the dry season inflates the outcome base rate (0.312
            # against the feature table's 0.173 for a LONGER window — the tell).
            season_end = pd.Timestamp(init.year, 9, 30)
            days = pd.date_range(init + pd.Timedelta(days=lo), init + pd.Timedelta(days=hi))
            have = [d for d in days if d in run7.index and d <= season_end]
            if len(have) < (hi - lo + 1):
                continue        # partial window — drop rather than bias
            if not have:
                continue
            # the outcome must be first-occurrence too
            truth = run7.loc[have].any(axis=0)
            if lo > 1:
                before = [d for d in pd.date_range(init + pd.Timedelta(days=1),
                                                   init + pd.Timedelta(days=lo - 1))
                          if d in run7.index]
                if before:
                    truth &= ~run7.loc[before].any(axis=0)
            truth = truth.astype(float)
            hi_t, lo_t = TARGET[lead]
            sl = oof[oof.date == init].set_index("cell_id")
            st = (sl[hi_t] if lo_t is None else (sl[hi_t] - sl[lo_t])).clip(0.0, 1.0)
            common = p_nwp.index.intersection(truth.index).intersection(st.index)
            if len(common) < 50:
                continue
            rows.append(pd.DataFrame({
                "year": init.year, "init": init, "lead": lead, "cell_id": common,
                "p_nwp": p_nwp.loc[common].to_numpy(),
                "p_stat": st.loc[common].to_numpy(),
                "y": truth.loc[common].to_numpy()}))
        log(f"  {f.stem}  rows so far {sum(len(r) for r in rows):,}")

    d = pd.concat(rows, ignore_index=True)
    log(f"{len(d):,} (P_nwp, P_stat, outcome) triples over {d.year.nunique()} seasons")
    # keep them: these are the only ground truth we have for the BLEND itself, which is
    # what W1's recalibration has to be validated against
    tp = PROC / "blend_triples.parquet"
    d.to_parquet(tp, index=False, compression="zstd")
    log(f"triples -> {tp.name}")

    grid = np.linspace(0, 1, 101)
    out = {}
    for lead, g in d.groupby("lead"):
        # leave-one-year-out: fit the weight on 9 seasons, score it on the 10th
        oos, fitted = [], []
        for yr in sorted(g.year.unique()):
            tr, te = g[g.year != yr], g[g.year == yr]
            bs = [M.brier(tr.y.to_numpy(), v * tr.p_nwp + (1 - v) * tr.p_stat) for v in grid]
            wv = float(grid[int(np.argmin(bs))])
            fitted.append(wv)
            oos.append(M.brier(te.y.to_numpy(), wv * te.p_nwp + (1 - wv) * te.p_stat))
        w_all = float(grid[int(np.argmin(
            [M.brier(g.y.to_numpy(), v * g.p_nwp + (1 - v) * g.p_stat) for v in grid]))])
        y = g.y.to_numpy()
        out[lead] = {
            "n": int(len(g)), "seasons": int(g.year.nunique()), "base_rate": float(y.mean()),
            "weight_all_data": w_all,
            "weight_loyo_mean": float(np.mean(fitted)),
            "weight_loyo_sd": float(np.std(fitted)),
            "brier_stat_only": M.brier(y, g.p_stat.to_numpy()),
            "brier_nwp_only": M.brier(y, g.p_nwp.to_numpy()),
            "brier_blend_oos": float(np.mean(oos)),
            "bss_nwp_vs_stat": M.bss(y, g.p_nwp.to_numpy(), g.p_stat.to_numpy()),
        }
        o = out[lead]
        log(f"  {lead}: n={o['n']:,} base={o['base_rate']:.3f} "
            f"w_all={w_all:.2f} w_loyo={o['weight_loyo_mean']:.2f}+-{o['weight_loyo_sd']:.2f} "
            f"| Brier stat {o['brier_stat_only']:.4f} nwp {o['brier_nwp_only']:.4f} "
            f"blend(oos) {o['brier_blend_oos']:.4f}")

    Path(args.out).write_text(json.dumps(out, indent=1, default=float))
    log(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
