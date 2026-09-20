"""Score the cached NWP runs against what actually happened, once enough have accumulated.

The blend weights in pipeline/blend.py are a prior, not a measurement, because Open-Meteo
serves no EC46 hindcast — a seasonal request for a past window returns nulls, and our own
cache started on 2026-09-18. This script is how that gets fixed: every nightly run leaves
another forecast on disk, and once there are enough overlapping (forecast, outcome) pairs
it measures Brier skill per lead and prints the weights the evidence supports.

Until it has data it says so and exits, rather than emitting a number nobody measured.
"""

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

from varshadrishti.pipeline import nwp as N  # noqa: E402
from varshadrishti.pipeline import observations as O  # noqa: E402

CACHE = ROOT / "data" / "cache"
MIN_RUNS = 30  # below this any "skill" is noise; say so instead of reporting it


def outcomes(obs: pd.DataFrame, start: pd.Timestamp) -> dict:
    """What actually happened, per cell per lead week, from observed rainfall."""
    from varshadrishti.features import labels as L

    out = {}
    dry = obs < L.RAINY_DAY_MM
    for lead, (a, b) in N.LEADS.items():
        win = obs.loc[start + pd.Timedelta(days=a): start + pd.Timedelta(days=b)]
        if win.empty:
            continue
        d = dry.loc[win.index]
        run7 = d.rolling(7, min_periods=7).sum().max() >= 7
        out[f"p_dry7_{lead}"] = run7.astype(float)
        out[f"p_heavy_{lead}"] = (win >= L.HEAVY_MM).any().astype(float)
    return out


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--model", default="ec46")
    a.add_argument("--min-runs", type=int, default=MIN_RUNS)
    args = a.parse_args()

    runs = sorted(p.stem for p in (CACHE / args.model).glob("*.json"))
    obs_days = sorted(p.stem for p in (CACHE / "obs").glob("*.json"))
    usable = [r for r in runs if any(o > r for o in obs_days)]

    print(f"{args.model}: {len(runs)} cached runs, {len(obs_days)} observation days, "
          f"{len(usable)} with any later observation")
    if len(usable) < args.min_runs:
        print(f"\nNOT ENOUGH DATA. Need {args.min_runs} verifiable runs, have {len(usable)}.")
        print("The blend weights stay provisional until this passes — see")
        print("src/varshadrishti/pipeline/blend.py. Every nightly run adds one.")
        return 0

    print("\nverifying...")   # reached only once the archive is deep enough
    rows = []
    for r in usable:
        start = pd.Timestamp(r)
        obs = O.fetch_recent([], r, use_cache=True)
        got = outcomes(obs, start)
        pred = N.probabilities(args.model, r, pd.Series(dtype=float))
        for slot, truth in got.items():
            if slot in pred.columns:
                common = truth.index.intersection(pred.index)
                rows.append(pd.DataFrame({"slot": slot, "run": r,
                                          "p": pred.loc[common, slot].to_numpy(),
                                          "y": truth.loc[common].to_numpy()}))
    df = pd.concat(rows, ignore_index=True)
    print(f"{len(df):,} (forecast, outcome) pairs\n")
    for slot, g in df.groupby("slot"):
        bs = float(np.mean((g.p - g.y) ** 2))
        base = float(g.y.mean())
        ref = float(np.mean((base - g.y) ** 2))
        print(f"  {slot:16s} n={len(g):>7,}  BS {bs:.4f}  BSS vs base rate "
              f"{1 - bs / ref if ref else float('nan'):+.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
