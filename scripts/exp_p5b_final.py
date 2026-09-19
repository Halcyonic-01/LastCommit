"""Confirmation run + lead curve.

The ablation compared models through their MARGINAL confidence intervals, which overlap
because both carry the same 34-season sampling noise. Both models see identical folds, so
the right test is PAIRED: resample years and score the DIFFERENCE. That is much tighter
and is what decides whether dropping ENSO/IOD is real.
"""

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

import exp_p5b as E  # noqa: E402
from varshadrishti.model import metrics as M  # noqa: E402

OUT = ROOT / "logs" / "p5b"
CHALLENGER = ["local", "regional", "seasonal", "clim", "mjo"]          # no enso_iod
INCUMBENT = ["local", "regional", "seasonal", "clim", "mjo", "enso_iod"]
BAGGING = dict(subsample=0.6, subsample_freq=1, colsample_bytree=0.6)
LEADS = [1, 3, 7, 10, 14, 21, 28]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def paired_bss_delta(y, p_new, p_old, ref, years_col, n_boot=2000, seed=0):
    """Resample YEARS and score BSS(new) - BSS(old) on the same resample each time."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(years_col)
    idx_by = {g: np.flatnonzero(years_col == g) for g in uniq}
    out = []
    for _ in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        i = np.concatenate([idx_by[g] for g in pick])
        out.append(M.bss(y[i], p_new[i], ref[i]) - M.bss(y[i], p_old[i], ref[i]))
    out = np.array(out)
    return {"delta": float(out.mean()), "ci95": [float(np.percentile(out, 2.5)),
                                                 float(np.percentile(out, 97.5))],
            "p_worse": float((out <= 0).mean())}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df, years, fc = E.load_everything()
    log(f"{len(df):,} rows loaded")
    results = {}

    # --- head to head, paired -------------------------------------------------
    for tgt in E.HEADLINE:
        log(f"=== {tgt}: incumbent vs challenger (paired) ===")
        a = E.run(df, years, fc, "inc", INCUMBENT, {}, [tgt], boot=400, keep_oof=True)[tgt]
        b = E.run(df, years, fc, "chl", CHALLENGER, BAGGING, [tgt], boot=400, keep_oof=True)[tgt]
        y = df[tgt].to_numpy(float)
        pair = paired_bss_delta(y, np.array(b["_oof"]), np.array(a["_oof"]),
                                np.array(a["_ref"]), df["year"].to_numpy())
        for d in (a, b):
            d.pop("_oof", None)
            d.pop("_ref", None)
        results[tgt] = {"incumbent": a, "challenger": b, "paired": pair}
        log(f"  incumbent  bss {a['bss']:+.4f}  pos {a['positive_seasons']}/34")
        log(f"  challenger bss {b['bss']:+.4f}  pos {b['positive_seasons']}/34")
        log(f"  PAIRED delta {pair['delta']:+.4f} ci({pair['ci95'][0]:+.4f},{pair['ci95'][1]:+.4f}) "
            f"P(challenger worse)={pair['p_worse']:.3f}")
        (OUT / "14_head_to_head.json").write_text(json.dumps(results, indent=1, default=float))

    # --- lead curve on the chosen configuration -------------------------------
    log("=== lead curve (challenger config) ===")
    curve = {}
    for h in LEADS:
        t = f"y_dry7_{h}"
        if t not in df.columns:
            log(f"  {t} absent, skipping")
            continue
        s = E.run(df, years, fc, f"lead{h}", CHALLENGER, BAGGING, [t], boot=400)[t]
        s.pop("reliability_curve", None)
        curve[str(h)] = s
        lo, hi = s["bss_ci95"]
        log(f"  lead {h:>2}d  base {s['base_rate']:.3f}  bss {s['bss']:+.4f} "
            f"ci({lo:+.4f},{hi:+.4f})  auc {s['roc_auc']:.3f}  pos {s['positive_seasons']}/34")
        (OUT / "15_lead_curve.json").write_text(json.dumps(curve, indent=1, default=float))

    log("FINAL COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
