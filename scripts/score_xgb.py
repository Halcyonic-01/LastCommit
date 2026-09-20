"""Score the shipped XGBoost models on held-out years and write models/metrics.json.

Replaces the LightGBM LOYO scorer. The published contract is unchanged - make_mock_
forecast.real_skill() still reads bss / bss_ci95 / roc_auc / reliability_curve - but the
evidence behind it is different and weaker, and that is stated rather than hidden:

  FIVE SEASONS, NOT THIRTY-FOUR. The boosters use a chronological split, so the only rows
  never seen in any form are 2020-2024. Bootstrap resampling whole years therefore draws
  from 5 units, not 34, and the intervals are correspondingly wide. A slot that fails to
  clear zero here has not been shown to be unskilful - it has been shown to be unproven.
  REFERENCE GETS EVERYTHING THE MODEL GOT. Climatology is built from 1991-2019, the same
  rows the boosters trained and early-stopped on, per (cell, sday) and smoothed +/-7 days.
  A reference denied that conditioning would flatter the model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti.features import extended as EX  # noqa: E402
from varshadrishti.model import predict_xgb as PX  # noqa: E402

TEST_YEARS = (2020, 2024)
CLIM_WINDOW = 7
N_BOOT = 2000
RELIABILITY_BINS = 20


def log(m: str) -> None:
    print(m, flush=True)


def climatology_reference(df: pd.DataFrame, target: str, fit_mask: np.ndarray) -> np.ndarray:
    """Per (cell, sday) base rate from the fitting years, smoothed across neighbouring days."""
    tr = df[fit_mask]
    tab = tr.groupby(["cell_id", "sday"])[target].agg(["sum", "count"])
    w = 2 * CLIM_WINDOW + 1
    num = tab["sum"].unstack("cell_id").rolling(w, center=True, min_periods=1).sum()
    den = tab["count"].unstack("cell_id").rolling(w, center=True, min_periods=1).sum()
    rate = num / den.replace(0, np.nan)

    out = rate.to_numpy()[rate.index.get_indexer(df["sday"]),
                          rate.columns.get_indexer(df["cell_id"])]
    return np.where(np.isnan(out), tr[target].mean(), out)


def _bss(y: np.ndarray, p: np.ndarray, ref: np.ndarray) -> float:
    return 1.0 - np.mean((p - y) ** 2) / np.mean((ref - y) ** 2)


def bootstrap_bss(y, p, ref, years, seed=0) -> tuple[float, float]:
    """95% interval, resampling whole SEASONS - neighbouring cells on a day are one event."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(years)
    idx = {u: np.flatnonzero(years == u) for u in uniq}
    draws = np.empty(N_BOOT)
    for b in range(N_BOOT):
        take = np.concatenate([idx[u] for u in rng.choice(uniq, len(uniq), replace=True)])
        draws[b] = _bss(y[take], p[take], ref[take])
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def reliability_curve(y: np.ndarray, p: np.ndarray) -> list[dict]:
    edges = np.linspace(0.0, 1.0, RELIABILITY_BINS + 1)
    which = np.clip(np.digitize(p, edges[1:-1]), 0, RELIABILITY_BINS - 1)
    out = []
    for b in range(RELIABILITY_BINS):
        m = which == b
        if not m.any():
            continue
        out.append({"p_mean": float(p[m].mean()), "observed": float(y[m].mean()),
                    "n": int(m.sum())})
    return out


def score(df: pd.DataFrame, target: str) -> dict:
    test_m = df.year.between(*TEST_YEARS).to_numpy()
    fit_m = ~test_m

    ref_all = climatology_reference(df, target, fit_m)
    test = df[test_m]
    y = test[target].to_numpy(float)
    p = PX.load(target).predict_proba(test, strict=True)
    ref = ref_all[test_m]
    years = test.year.to_numpy()

    brier, brier_clim = float(np.mean((p - y) ** 2)), float(np.mean((ref - y) ** 2))
    lo, hi = bootstrap_bss(y, p, ref, years)
    by_year = {int(u): round(_bss(y[years == u], p[years == u], ref[years == u]), 6)
               for u in np.unique(years)}

    obs = y.mean()
    return {
        "n": int(len(y)),
        "base_rate": float(obs),
        "brier": brier,
        "brier_climatology": brier_clim,
        "bss": 1.0 - brier / brier_clim,
        "bss_ci95": [lo, hi],
        "roc_auc": float(roc_auc_score(y, p)),
        "roc_auc_climatology": float(roc_auc_score(y, ref)),
        "uncertainty": float(obs * (1 - obs)),
        "reliability_curve": reliability_curve(y, p),
        "by_year": by_year,
        "positive_seasons": int(sum(v > 0 for v in by_year.values())),
        "n_seasons": len(by_year),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "models" / "metrics.json"))
    a = ap.parse_args()

    log("loading features + extended predictors")
    df = EX.attach(pd.read_parquet(ROOT / "data" / "processed" / "features.parquet"),
                   ecmwf=True, clean_climatology=True)

    out = {}
    for g in PX.GROUPS:
        for h in PX.HORIZONS:
            t = f"y_{g}_{h}"
            out[t] = score(df, t)
            r = out[t]
            log(f"  {t:20s} bss {r['bss']:+.4f}  ci95 ({r['bss_ci95'][0]:+.4f}, "
                f"{r['bss_ci95'][1]:+.4f})  auc {r['roc_auc']:.4f}  "
                f"{r['positive_seasons']}/{r['n_seasons']} seasons")

    out["_provenance"] = {
        "backend": "xgboost",
        "split": "chronological — train 1991-2015, val 2016-2019, test 2020-2024",
        "scored_on": f"{TEST_YEARS[0]}-{TEST_YEARS[1]} ({out['y_dry7_7']['n']:,} rows, 5 seasons)",
        "reference": "per-cell, per-season-day climatology from 1991-2019, smoothed +/-7 days",
        "bootstrap": f"{N_BOOT} draws resampling whole seasons; 5 seasons makes these wide",
        "calibration": "none — raw binary:logistic with a validation-tuned threshold",
    }
    Path(a.out).write_text(json.dumps(out, indent=1))
    log(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
