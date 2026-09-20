"""W1: does recalibrating the linear pool actually help? Decide it on real blend outcomes.

Ranjan & Gneiting (2010) prove a linear pool of calibrated forecasts is necessarily
uncalibrated. That theorem is not in doubt. What has been in doubt is whether the fix
helps HERE: the transform was validated only on a proxy (daily dry-day, climatology as
the calibrated side, base rate 0.616), and on a synthetic case it made reliability 5x
WORSE, because a fixed sharpening strength over-sharpens a pool that was not under-sharp.

data/processed/blend_triples.parquet is the first ground truth for the blend itself:
real P_nwp (GEFSv12), real P_stat (our out-of-fold prediction), real IMD outcome, at the
actual leads. Fit on five seasons, score on the sixth, repeat. If the transform does not
beat the plain pool out-of-sample, it stays off — permanently, with evidence.
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

from varshadrishti.model import metrics as M  # noqa: E402
from varshadrishti.pipeline import blend as BL  # noqa: E402

PROC = ROOT / "data" / "processed"
STRENGTHS = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 12.0]


def mean_preserving(p: np.ndarray, strength: float) -> np.ndarray:
    """Beta CDF with a:b solved so the mean forecast is unchanged — sharpen, don't shift."""
    from scipy.optimize import brentq
    from scipy.stats import beta as bd

    q = np.clip(p, 1e-6, 1 - 1e-6)
    target = float(q.mean())

    def gap(frac):
        a = max(1e-3, frac * strength)
        return float(bd.cdf(q, a, max(1e-3, strength - a)).mean()) - target

    try:
        frac = brentq(gap, 0.02, 0.98, xtol=1e-4)
    except ValueError:
        return p
    return np.clip(bd.cdf(q, frac * strength, strength - frac * strength), 1e-4, 1 - 1e-4)


def main():
    f = PROC / "blend_triples.parquet"
    if not f.exists():
        print("no blend triples — run scripts/derive_blend_weights.py")
        return 1
    d = pd.read_parquet(f)
    print(f"{len(d):,} triples, {d.year.nunique()} seasons\n")

    out = {}
    for lead, g in d.groupby("lead"):
        w = BL.NWP_WEIGHT[lead]
        g = g.copy()
        g["pool"] = w * g.p_nwp + (1 - w) * g.p_stat
        y = g.y.to_numpy()

        # leave-one-season-out: pick the strength on five seasons, score it on the sixth
        base_bs, tr_bs, picked = [], [], []
        for yr in sorted(g.year.unique()):
            fit, te = g[g.year != yr], g[g.year == yr]
            best = min(STRENGTHS,
                       key=lambda s: M.brier(fit.y.to_numpy(),
                                             mean_preserving(fit.pool.to_numpy(), s)))
            picked.append(best)
            base_bs.append(M.brier(te.y.to_numpy(), te.pool.to_numpy()))
            tr_bs.append(M.brier(te.y.to_numpy(),
                                 mean_preserving(te.pool.to_numpy(), best)))

        # paired bootstrap over seasons on the DIFFERENCE
        rng = np.random.default_rng(0)
        yrs = np.array(sorted(g.year.unique()))
        deltas = []
        for _ in range(2000):
            pick = rng.choice(len(yrs), len(yrs), replace=True)
            deltas.append(np.mean([base_bs[i] - tr_bs[i] for i in pick]))
        lo, hi = np.percentile(deltas, [2.5, 97.5])

        rel_pool = M.murphy(y, g.pool.to_numpy(), bins=200)["reliability"]
        rel_tr = M.murphy(y, mean_preserving(g.pool.to_numpy(), float(np.median(picked))),
                          bins=200)["reliability"]
        out[lead] = {
            "brier_pool_oos": float(np.mean(base_bs)),
            "brier_recal_oos": float(np.mean(tr_bs)),
            "delta": float(np.mean(base_bs) - np.mean(tr_bs)),
            "ci95": [float(lo), float(hi)],
            "p_worse": float(np.mean(np.array(deltas) <= 0)),
            "strength_median": float(np.median(picked)),
            "reliability_pool_200bin": rel_pool,
            "reliability_recal_200bin": rel_tr,
        }
        o = out[lead]
        print(f"  {lead}: pool {o['brier_pool_oos']:.5f} -> recal {o['brier_recal_oos']:.5f} "
              f"| delta {o['delta']:+.5f} ci({lo:+.5f},{hi:+.5f}) P(worse)={o['p_worse']:.3f} "
              f"| rel {rel_pool:.5f} -> {rel_tr:.5f}")

    helps = [k for k, v in out.items() if v["ci95"][0] > 0]
    print(f"\nVERDICT: recalibration helps out-of-sample at {helps or 'NO LEAD'}")
    (ROOT / "logs" / "w1_recalibration.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
