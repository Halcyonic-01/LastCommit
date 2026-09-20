"""Pre-registered: do ENSO/IOD help at LONG lead only?

P5b rejected them pooled across all leads. That does not settle day 28: by then the local
rainfall state has largely decayed, and slow seasonal forcing is the one thing that has
not. Different hypothesis, so it gets its own paired test rather than a reinstatement on
the strength of the PS naming them.

Fixed before running: three targets, two configurations, paired bootstrap on years, and
the decision rule — keep ENSO/IOD at long lead only if the paired CI clears zero.
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
from exp_p5b_final import paired_bss_delta  # noqa: E402

OUT = ROOT / "logs" / "p5b"
WITHOUT = ["local", "regional", "seasonal", "clim", "mjo"]
WITH = WITHOUT + ["enso_iod"]
BAG = dict(subsample=0.6, subsample_freq=1, colsample_bytree=0.6)
TARGETS = ["y_dry7_28", "y_onset_28", "y_false_onset_28"]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    df, years, fc = E.load_everything()
    log(f"{len(df):,} rows | long-lead ENSO/IOD test on {TARGETS}")
    res = {}
    for t in TARGETS:
        a = E.run(df, years, fc, "no_enso", WITHOUT, BAG, [t], boot=400, keep_oof=True)[t]
        b = E.run(df, years, fc, "with_enso", WITH, BAG, [t], boot=400, keep_oof=True)[t]
        pair = paired_bss_delta(df[t].to_numpy(float), np.array(b["_oof"]),
                                np.array(a["_oof"]), np.array(a["_ref"]),
                                df["year"].to_numpy())
        for d in (a, b):
            d.pop("_oof", None)
            d.pop("_ref", None)
        res[t] = {"without": a, "with": b, "paired": pair}
        log(f"  {t:18s} without {a['bss']:+.4f} | with {b['bss']:+.4f} | "
            f"paired {pair['delta']:+.4f} ci({pair['ci95'][0]:+.4f},{pair['ci95'][1]:+.4f}) "
            f"P(with worse)={pair['p_worse']:.3f}")
        (OUT / "16_longlead_ensoiod.json").write_text(json.dumps(res, indent=1, default=float))

    keep = [t for t, r in res.items() if r["paired"]["ci95"][0] > 0]
    log(f"DECISION: ENSO/IOD helps at long lead for {keep or 'NO TARGET'}")
    log("FINAL COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
