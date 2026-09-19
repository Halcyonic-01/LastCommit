"""Probabilistic verification. Brier, its Murphy decomposition, and skill vs climatology.

Accuracy is meaningless here: "no dry spell" is right 60% of the time by saying nothing.
Every number below is scored against a climatology that already knows the local base rate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RELIABILITY_BINS = 10


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def bss(y: np.ndarray, p: np.ndarray, p_ref: np.ndarray) -> float:
    """1 - BS/BS_ref. Zero means the model adds nothing a climatology did not already know.

    Mason (2004): with climatology as reference this is a NEGATIVELY biased estimator, so a
    small positive value is worth more than it looks and a small negative one is not proof
    of failure. Report the interval, not just the point.
    """
    ref = brier(y, p_ref)
    return float("nan") if ref == 0 else 1.0 - brier(y, p) / ref


def murphy(y: np.ndarray, p: np.ndarray, bins: int = RELIABILITY_BINS) -> dict:
    """BS = reliability - resolution + uncertainty. Separates calibration from discrimination.

    Exact only when grouping by unique forecast values; with 10 bins it reconstructs BS to
    ~1e-3, the within-bin spread. Read the three terms, not the sum.
    """
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    base = y.mean()
    n = len(y)

    rel = res = 0.0
    for b in range(bins):
        m = idx == b
        nk = int(m.sum())
        if not nk:
            continue
        pk, ok = p[m].mean(), y[m].mean()
        rel += nk * (pk - ok) ** 2
        res += nk * (ok - base) ** 2
    return {"reliability": rel / n, "resolution": res / n, "uncertainty": float(base * (1 - base))}


def reliability_curve(y: np.ndarray, p: np.ndarray, bins: int = RELIABILITY_BINS) -> pd.DataFrame:
    """Forecast probability vs observed frequency, with the count that earns each point."""
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        rows.append({"bin": b, "p_mid": (edges[b] + edges[b + 1]) / 2,
                     "p_mean": float(p[m].mean()), "observed": float(y[m].mean()), "n": int(m.sum())})
    return pd.DataFrame(rows)


def roc_auc(y: np.ndarray, p: np.ndarray) -> float:
    """Rank-based, so calibration cannot help or hurt it — pure discrimination."""
    if len(np.unique(y)) < 2:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), float)
    ranks[order] = np.arange(1, len(p) + 1)
    # average ranks over ties, or tied scores inflate the result
    s = pd.Series(p).groupby(pd.Series(p)).transform("size").to_numpy()
    if (s > 1).any():
        ranks = pd.Series(ranks).groupby(pd.Series(p)).transform("mean").to_numpy()
    n1 = float(y.sum())
    n0 = float(len(y) - n1)
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def block_bootstrap_bss(y, p, p_ref, groups, n_boot: int = 500, seed: int = 0) -> tuple:
    """CI resampling whole YEARS, never rows.

    Adjacent days and neighbouring cells in one season are the same weather event, so a
    row-wise bootstrap treats ~1.3M correlated rows as independent and returns an interval
    far too narrow to mean anything (Wilks 2010).
    """
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    by_group = {g: np.flatnonzero(groups == g) for g in uniq}

    out = []
    for _ in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([by_group[g] for g in pick])
        out.append(bss(y[idx], p[idx], p_ref[idx]))
    lo, hi = np.percentile(out, [2.5, 97.5])
    return float(lo), float(hi)


def summarise(y, p, p_ref, groups=None, n_boot: int = 0) -> dict:
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    p_ref = np.asarray(p_ref, float)
    d = murphy(y, p)
    out = {
        "n": int(len(y)),
        "base_rate": float(y.mean()),
        "brier": brier(y, p),
        "brier_climatology": brier(y, p_ref),
        "bss": bss(y, p, p_ref),
        "roc_auc": roc_auc(y, p),
        **d,
    }
    if n_boot and groups is not None:
        out["bss_ci95"] = block_bootstrap_bss(y, p, p_ref, np.asarray(groups), n_boot)
    return out
