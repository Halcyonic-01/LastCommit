"""Train, calibrate and score every target. Writes models/ + metrics.json.

Two different things come out of this, and conflating them is how projects end up quoting
a skill they do not have:

  THE HONEST SCORE comes from the leave-one-year-out run — each season predicted by a model
  that never saw it. That is what metrics.json reports and what the app shows.
  THE SHIPPED MODEL is refit on all 34 seasons. It should be a little better than the score
  says, because it has seen more. It is never scored on its own training data.
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
MODELS = ROOT / "models"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def build_fold_climatology(df):
    """Ingredients for per-fold climatology, plus the full-record version for shipping."""
    onset = pd.read_parquet(PROC / "onset_labels.parquet")
    years = sorted(df.year.unique())
    w = pd.read_parquet(PROC / "weights_imd_hoblis.parquet")
    pad = 0.3
    b = (w.lon.min() - pad, w.lat.min() - pad, w.lon.max() + pad, w.lat.max() + pad)
    rain = load_imd(min(years), max(years), bounds=b)
    rain = rain[[c for c in sorted(set(w.cell_id)) if c in rain.columns]]
    return FoldClimatology(rain, years, onset, df)


def fit_final(df, target, feats, n_estimators, params=None):
    """Refit on everything for deployment, at the iteration count LOYO actually settled on.

    Not PARAMS["n_estimators"]: that is the early-stopping ceiling, ~600, and every fold
    stopped nearer 90. Shipping the ceiling ships a model trained seven times past the
    point its own validation said to stop.
    """
    import lightgbm as lgb

    p = {**T.PARAMS, **(params or {}), "n_estimators": int(n_estimators)}
    model = lgb.LGBMClassifier(**p)
    model.fit(df[feats], df[target])
    return model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="*", default=T.TARGETS)
    ap.add_argument("--boot", type=int, default=400, help="block-bootstrap resamples")
    ap.add_argument("--shuffle-control", default="y_dry7_7",
                    help="target to re-run with labels shuffled; '' to skip")
    a = ap.parse_args()

    from sklearn.isotonic import IsotonicRegression

    MODELS.mkdir(exist_ok=True)
    df = pd.read_parquet(PROC / "features.parquet")
    years = sorted(df.year.unique())
    feats = T.feature_names(df)
    log(f"{len(df):,} rows | {len(years)} seasons | {len(feats)} features")

    # Merge rather than overwrite: adding one target should not force a 30-minute rerun
    # of the nine already scored, and a half-written metrics.json is a silent regression.
    out = json.loads((MODELS / "metrics.json").read_text()) if (MODELS / "metrics.json").exists() else {}
    oof_path = PROC / "oof_predictions.parquet"
    oof_store = (pd.read_parquet(oof_path).to_dict("series") if oof_path.exists()
                 else {"date": df["date"], "cell_id": df["cell_id"], "year": df["year"]})

    import lightgbm as lgb

    log("building fold climatology ingredients")
    fc = build_fold_climatology(df)
    base_cols = [c for c in feats if c not in CLIM_COLS]
    use_clim = [c for c in feats if c in CLIM_COLS]

    # Fold-outer: climatology is rebuilt once per fold and reused by every target, rather
    # than 11 times over. Each fold's climatology comes from years != hold.
    log(f"LOYO over {len(years)} folds x {len(a.targets)} targets")
    oof_raw = {t: np.full(len(df), np.nan) for t in a.targets}
    ref_all = {t: np.full(len(df), np.nan) for t in a.targets}
    iters = {t: [] for t in a.targets}

    for fold, hold in enumerate(years):
        X = df[base_cols].copy()
        X[use_clim] = fc.for_fold(hold)[use_clim].to_numpy()
        tr_years = [y for y in years if y != hold]
        val_years = T._inner_val_years(tr_years, fold)
        fit_m = df.year.isin([y for y in tr_years if y not in val_years]).to_numpy()
        val_m = df.year.isin(val_years).to_numpy()
        te_m = (df.year == hold).to_numpy()
        for target in a.targets:
            yv = df[target].to_numpy(float)
            mdl = lgb.LGBMClassifier(**T.PARAMS)
            mdl.fit(X[fit_m], yv[fit_m], eval_X=X[val_m], eval_y=yv[val_m],
                    eval_metric="binary_logloss",
                    callbacks=[lgb.early_stopping(T.EARLY_STOP, verbose=False)])
            oof_raw[target][te_m] = mdl.predict_proba(X[te_m])[:, 1]
            ref_all[target][te_m] = reference_from_fold(df, target, hold, years)[te_m]
            iters[target].append(int(mdl.best_iteration_ or T.PARAMS["n_estimators"]))
        log(f"  fold {hold} done")

    # the SHIPPED model sees full-record climatology, because inference will too
    df_ship = df.copy()
    df_ship[use_clim] = fc.for_inference()[use_clim].to_numpy()

    for target in a.targets:
        t0 = time.time()
        y = df[target].to_numpy(float)
        ref = ref_all[target]
        oof = pd.Series(oof_raw[target])
        info = [{"best_iter": i} for i in iters[target]]
        cal = T.calibrate_oof(oof, df[target], df["year"], years)

        s = M.summarise(y, cal.to_numpy(), ref, groups=df["year"].to_numpy(), n_boot=a.boot)
        s["brier_raw"] = M.brier(y, oof.to_numpy())
        s["bss_raw"] = M.bss(y, oof.to_numpy(), ref)
        s["roc_auc_climatology"] = M.roc_auc(y, ref)
        s["median_best_iter"] = int(np.median([i["best_iter"] for i in info]))
        s["reliability_curve"] = M.reliability_curve(y, cal.to_numpy()).to_dict("records")
        # Onset skill is flattered by persistence: consecutive 5-day windows overlap by
        # four days, so "a sowing rain in the next week" is easy while one is falling.
        # The decision is only live BEFORE the season's first sowing rain — score that too.
        pre = (df["wet_spell_seen"] == 0).to_numpy()
        if pre.sum() > 1000:
            s["pre_onset"] = {
                "n": int(pre.sum()),
                "base_rate": float(y[pre].mean()),
                "bss": M.bss(y[pre], cal[pre].to_numpy(), ref[pre]),
                "roc_auc": M.roc_auc(y[pre], cal[pre].to_numpy()),
            }
        s["by_year"] = {
            str(yr): M.bss(y[(df.year == yr).to_numpy()], cal[(df.year == yr).to_numpy()].to_numpy(),
                           ref[(df.year == yr).to_numpy()])
            for yr in years
        }
        out[target] = s
        oof_store[target] = cal.to_numpy()
        oof_store[f"{target}_clim"] = ref

        # ship: model refit on everything, isotonic refit on all out-of-fold predictions
        model = fit_final(df_ship, target, feats, s["median_best_iter"])
        model.booster_.save_model(str(MODELS / f"{target}.txt"))
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(oof, y)
        np.savez(MODELS / f"{target}_isotonic.npz", x=iso.X_thresholds_, y=iso.y_thresholds_)

        log(f"{target:12s} bss {s['bss']:+.4f} ci{tuple(round(v,3) for v in s['bss_ci95'])} "
            f"auc {s['roc_auc']:.3f} (clim {s['roc_auc_climatology']:.3f}) "
            f"rel {s['reliability']:.5f} [{time.time()-t0:.0f}s]")

    if a.shuffle_control:
        tgt = a.shuffle_control
        log(f"control: {tgt} with labels shuffled within each season")
        y_s = T.shuffled_labels(df, tgt, years, seed=0)
        # the reference has to describe the SAME shuffled world, or the control wins for free
        shuf = df.assign(**{tgt: y_s})
        ref = T.climatology_reference(shuf, tgt, years).to_numpy()
        oof_s, _ = T.loyo_predict(df.assign(**{c: fc.for_inference()[c].to_numpy()
                                                for c in use_clim}),
                                  tgt, feats, years, shuffle_labels=True, seed=0)
        b = M.bss(y_s, oof_s.to_numpy(), ref)
        out["_shuffle_control"] = {"target": tgt, "bss": b}
        log(f"control bss {b:+.4f}  (must be ~0; anything clearly positive is leakage)")

    (MODELS / "metrics.json").write_text(json.dumps(out, indent=1, default=float))
    pd.DataFrame(oof_store).to_parquet(PROC / "oof_predictions.parquet", index=False,
                                       compression="zstd")
    log(f"wrote models/metrics.json and data/processed/oof_predictions.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
