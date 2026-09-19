"""Run the whole P5b experiment programme in one process. Results -> logs/p5b/*.json.

Pre-registered before any of it ran: the ablation grid, the three regularisation configs,
the six candidate features and the lead curve are all fixed here. Nothing is added later
on the strength of a result, which is the only defence against tuning on a 34-season set.
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

OUT = ROOT / "logs" / "p5b"
BOOT_FAST = 200   # screening runs
BOOT_FULL = 400   # anything quoted as a result


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def add_candidates(df: pd.DataFrame) -> pd.DataFrame:
    """Six pre-registered features. Each varies DAILY, so its effective sample size is the
    number of days, not the 34 seasons that made oni/dmi year-labels in disguise."""
    d = df
    # 1-2. break coverage: a monsoon break is defined by WIDESPREAD dryness, not local
    daily = d.groupby("date").agg(
        _dryfrac=("rain_1d", lambda s: float((s < 2.5).mean())),
        _r30=("rain_30d", "mean"))
    d = d.merge(daily.rename(columns={"_dryfrac": "reg_dry_frac", "_r30": "reg_rain_30d"}),
                left_on="date", right_index=True, how="left")
    # 3-4. change, not level: is this cell/region drying or wetting?
    d["rain_7d_trend"] = d["rain_7d"] - (d["rain_14d"] - d["rain_7d"])
    reg_tr = d.groupby("date")["rain_7d_trend"].mean().rename("reg_rain_7d_trend")
    d = d.merge(reg_tr, left_on="date", right_index=True, how="left")
    # 5-6. MJO phase is circular; 8 and 1 are neighbours, which an integer split cannot see
    ph = d["mjo_phase"].to_numpy(float)
    amp = d["mjo_amp"].to_numpy(float)
    d["mjo_sin"] = np.sin(2 * np.pi * ph / 8.0) * amp
    d["mjo_cos"] = np.cos(2 * np.pi * ph / 8.0) * amp
    return d


CANDIDATES = ["reg_dry_frac", "reg_rain_30d", "rain_7d_trend", "reg_rain_7d_trend",
              "mjo_sin", "mjo_cos"]

ABLATIONS = {
    "02_local_only":        ["local"],
    "03_local_regional":    ["local", "regional"],
    "04_plus_seasonal":     ["local", "regional", "seasonal"],
    "05_plus_clim":         ["local", "regional", "seasonal", "clim"],
    "06_plus_mjo":          ["local", "regional", "seasonal", "clim", "mjo"],
    "07_plus_ensoiod":      ["local", "regional", "seasonal", "clim", "mjo", "enso_iod"],
    "08_no_clim":           ["local", "regional", "seasonal", "mjo"],
}

# Chosen from the 34-independent-units argument, NOT searched against LOYO.
# min_child_samples counts ROWS; one season is ~39k rows, so 200 never constrained anything.
REGULARISATION = {
    "09_reg_bagging_by_year": dict(subsample=0.6, subsample_freq=1, colsample_bytree=0.6),
    "10_reg_shallow":         dict(num_leaves=15, max_depth=5, min_child_samples=5000),
    "11_reg_strong":          dict(num_leaves=15, max_depth=5, min_child_samples=20000,
                                   reg_lambda=20.0, learning_rate=0.03),
}

FULL = ["local", "regional", "seasonal", "clim", "enso_iod", "mjo"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log("loading once for the whole programme")
    df, years, fc = E.load_everything()
    df = add_candidates(df)
    E.GROUPS["cand"] = CANDIDATES
    log(f"{len(df):,} rows | +{len(CANDIDATES)} candidate features")

    plan = []
    for name, groups in ABLATIONS.items():
        plan.append((name, groups, {}, E.HEADLINE, BOOT_FAST))
    for name, params in REGULARISATION.items():
        plan.append((name, FULL, params, ["y_dry7_7"], BOOT_FAST))
    # candidates measured individually against the corrected baseline, then together
    for i, c in enumerate(CANDIDATES):
        E.GROUPS[f"c{i}"] = [c]
        plan.append((f"12_cand_{c}", FULL + [f"c{i}"], {}, ["y_dry7_7"], BOOT_FAST))
    plan.append(("13_cand_all", FULL + ["cand"], {}, E.HEADLINE, BOOT_FULL))

    for name, groups, params, targets, boot in plan:
        f = OUT / f"{name}.json"
        if f.exists():
            log(f"skip {name} (already done)")
            continue
        t0 = time.time()
        res = E.run(df, years, fc, name, groups, params, targets, boot)
        f.write_text(json.dumps(res, indent=1, default=float))
        for t, s in res.items():
            lo, hi = s["bss_ci95"]
            log(f"  {name:26s} {t:11s} bss {s['bss']:+.4f} ci({lo:+.3f},{hi:+.3f}) "
                f"auc {s['roc_auc']:.3f} pos {s['positive_seasons']}/34 "
                f"jul {s['by_month']['7']:+.3f} sep {s['by_month']['9']:+.3f} [{time.time()-t0:.0f}s]")
    log("PROGRAMME COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
