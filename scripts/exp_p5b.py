"""One LOYO protocol, many experiments. Every result in logs/p5b/<name>.json.

Fold-internal climatology: for fold H, climatology comes from years != H and is applied to
training and test rows alike. Nothing about the held-out year reaches a training feature.
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

from varshadrishti.data.rainfall import load_imd  # noqa: E402
from varshadrishti.features.climatology import CLIM_COLS, FoldClimatology, reference_from_fold  # noqa: E402
from varshadrishti.model import metrics as M  # noqa: E402
from varshadrishti.model import train as T  # noqa: E402

PROC = ROOT / "data" / "processed"
OUT = ROOT / "logs" / "p5b"

GROUPS = {
    "local": ["rain_1d", "rain_3d", "rain_7d", "rain_14d", "rain_30d", "wet_days_30d",
              "days_since_rain", "wet_spell_today", "wet_spell_seen",
              "days_since_wet_spell", "spell_deficit", "onset_threshold_mm"],
    "regional": ["reg_rain_7d", "reg_dry", "rain_7d_vs_region"],
    "seasonal": ["doy"],
    "clim": CLIM_COLS,
    "enso_iod": ["oni", "dmi", "nino34_anom"],
    "mjo": ["rmm1", "rmm2", "mjo_amp", "mjo_phase"],
}
ALL_GROUPS = list(GROUPS)
HEADLINE = ["y_dry7_7", "y_onset_14", "y_heavy_7"]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_everything():
    df = pd.read_parquet(PROC / "features.parquet")
    onset = pd.read_parquet(PROC / "onset_labels.parquet")
    years = sorted(df.year.unique())
    w = pd.read_parquet(PROC / "weights_imd_hoblis.parquet")
    pad = 0.3
    bounds = (w.lon.min() - pad, w.lat.min() - pad, w.lon.max() + pad, w.lat.max() + pad)
    rain = load_imd(min(years), max(years), bounds=bounds)
    rain = rain[[c for c in sorted(set(w.cell_id)) if c in rain.columns]]
    fc = FoldClimatology(rain, years, onset, df)
    return df, years, fc


def run(df, years, fc, name, groups, params=None, targets=HEADLINE, boot=400,
        seed=0, keep_oof=False):
    """LOYO with fold-internal climatology. Returns per-target metric dicts."""
    import lightgbm as lgb

    feats = [c for g in groups for c in GROUPS[g]]
    p = {**T.PARAMS, **(params or {})}
    base_cols = [c for c in feats if c not in CLIM_COLS]
    use_clim = [c for c in feats if c in CLIM_COLS]

    oof = {t: np.full(len(df), np.nan) for t in targets}
    ref = {t: np.full(len(df), np.nan) for t in targets}
    iters = []

    for fold, hold in enumerate(years):
        X = df[base_cols].copy()
        if use_clim:
            X[use_clim] = fc.for_fold(hold)[use_clim].to_numpy()

        tr_years = [y for y in years if y != hold]
        val_years = T._inner_val_years(tr_years, fold)
        fit_m = df.year.isin([y for y in tr_years if y not in val_years]).to_numpy()
        val_m = df.year.isin(val_years).to_numpy()
        te_m = (df.year == hold).to_numpy()

        for t in targets:
            y = df[t].to_numpy(float)
            mdl = lgb.LGBMClassifier(**p)
            mdl.fit(X[fit_m], y[fit_m], eval_X=X[val_m], eval_y=y[val_m],
                    eval_metric="binary_logloss",
                    callbacks=[lgb.early_stopping(T.EARLY_STOP, verbose=False)])
            oof[t][te_m] = mdl.predict_proba(X[te_m])[:, 1]
            ref[t][te_m] = reference_from_fold(df, t, hold, years)[te_m]
            iters.append(int(mdl.best_iteration_ or p["n_estimators"]))

    res = {}
    for t in targets:
        y = df[t].to_numpy(float)
        cal = T.calibrate_oof(pd.Series(oof[t]), df[t], df["year"], years).to_numpy()
        s = M.summarise(y, cal, ref[t], groups=df["year"].to_numpy(), n_boot=boot)
        s["by_year"] = {str(yr): M.bss(y[(df.year == yr).to_numpy()],
                                       cal[(df.year == yr).to_numpy()],
                                       ref[t][(df.year == yr).to_numpy()]) for yr in years}
        s["positive_seasons"] = sum(1 for v in s["by_year"].values() if v > 0)
        mth = pd.to_datetime(df["date"]).dt.month.to_numpy()
        s["by_month"] = {str(mm): M.bss(y[mth == mm], cal[mth == mm], ref[t][mth == mm])
                         for mm in (6, 7, 8, 9)}
        s["reliability_curve"] = M.reliability_curve(y, cal).to_dict("records")
        s["median_best_iter"] = int(np.median(iters))
        s["features"] = feats
        s["groups"] = groups
        if keep_oof:  # for a PAIRED comparison the two runs must share folds and reference
            s["_oof"] = cal.tolist()
            s["_ref"] = ref[t].tolist()
        res[t] = s
    return res


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--name", required=True)
    a.add_argument("--groups", nargs="*", default=ALL_GROUPS)
    a.add_argument("--targets", nargs="*", default=HEADLINE)
    a.add_argument("--params", default="{}", help="JSON overrides for LightGBM")
    a.add_argument("--boot", type=int, default=400)
    args = a.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    log(f"loading (experiment: {args.name})")
    df, years, fc = load_everything()
    log(f"{len(df):,} rows | groups={args.groups}")

    t0 = time.time()
    res = run(df, years, fc, args.name, args.groups, json.loads(args.params),
              args.targets, args.boot)
    for t, s in res.items():
        lo, hi = s["bss_ci95"]
        log(f"  {t:12s} bss {s['bss']:+.4f} ci({lo:+.3f},{hi:+.3f}) auc {s['roc_auc']:.3f} "
            f"pos {s['positive_seasons']}/34 jul {s['by_month']['7']:+.3f} sep {s['by_month']['9']:+.3f}")
    (OUT / f"{args.name}.json").write_text(json.dumps(res, indent=1, default=float))
    log(f"-> logs/p5b/{args.name}.json  [{time.time()-t0:.0f}s]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
