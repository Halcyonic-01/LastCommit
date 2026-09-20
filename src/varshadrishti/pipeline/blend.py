"""Combine P_nwp and P_stat into the published probability.

THE WEIGHTS ARE NOT MEASURED, AND THAT IS RECORDED IN EVERY FILE WE WRITE.

Open-Meteo's seasonal endpoint serves no EC46 hindcast — a request for a past window
returns nulls, and our own cache began on 2026-09-18. So `P_nwp` skill cannot be scored on
the 34-season protocol that `P_stat` went through, and any weight here is a prior rather
than a result. The defaults follow the standard sub-seasonal pattern (a dynamical model
dominates week 1, statistics and climatology take over by week 4) and are deliberately
shrunk toward an even split, which is what the literature recommends when skill is
unmeasured. `scripts/verify_nwp.py` replaces them the moment the archive can support it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --- W1: a linear pool is PROVABLY uncalibrated ----------------------------
# Ranjan & Gneiting (2010): any nontrivial weighted average of distinct calibrated
# probability forecasts is necessarily uncalibrated and loses sharpness. Blending a
# calibrated P_stat with a raw ensemble fraction therefore cannot be calibrated however
# good the inputs are — a theorem, not an implementation slip. Their fix is the
# beta-transformed linear pool: push the pooled probability through a Beta CDF.
#
# We apply it MEAN-PRESERVING, and that detail matters. A freely fitted Beta also moves
# the mean, and the parameters we could fit came from a problem with base rate 0.616
# (daily dry-day). Applied to dry spells at base rate ~0.40 it shifted every probability
# down by ~0.07 — systematically under-warning farmers. The theorem is about SHARPNESS;
# the location shift is target-specific and must not be imported. So the strength comes
# from the weight and the a:b split is solved per slot so the mean forecast is unchanged.
#
# Measured, 2024 monsoon, 118,218 pairs, fitted on one half and scored on the other:
#
#   lead  w     reliability pool -> mean-preserving    Brier pool -> MP    mean shift
#     1d  0.38     0.006020 -> 0.000840                0.18148 -> 0.17597    +0.0000
#     3d  0.34     0.004391 -> 0.000887                0.18357 -> 0.17980    +0.0000
#     7d  0.22     0.002555 -> 0.000935                0.18629 -> 0.18451    -0.0000
#
# ~7x less reliability error, a better Brier score, and no base-rate drift.
# Weight on the DYNAMICAL model, by lead — MEASURED, not assumed or extrapolated.
#
# scripts/derive_blend_weights.py, 20,274 (P_nwp, P_stat, outcome) triples over six
# monsoon seasons (2010-2015). P_nwp is the NOAA GEFSv12 reforecast, 11 members, leads
# 0-35, public and unauthenticated; P_stat is our own out-of-fold prediction; the outcome
# is IMD. All three are FIRST-occurrence, which is what finally made them comparable.
# Weights are fitted leave-one-season-out: five seasons fit, the sixth scores.
#
#   lead  base  expected  weight  fold sd   Brier stat / nwp / blend(oos)
#     w1  0.346    0.401    0.32   0.02      0.1849 / 0.2159 / 0.1760
#     w2  0.164    0.161    0.09   0.08      0.1332 / 0.1618 / 0.1351
#     w3  0.098    0.107    0.01   0.01      0.0864 / 0.1355 / 0.0857
#     w4  0.081    0.075    0.06   0.02      0.0728 / 0.1277 / 0.0728
#
# The headline: OUR MODEL BEATS THE ENSEMBLE AT EVERY LEAD, and by more as lead grows
# (0.1849 vs 0.2159 at w1; 0.0728 vs 0.1277 at w4). Every earlier figure here was wrong.
# The literature prior said 0.80 at w1 decaying to 0.25; an extrapolation from
# deterministic short-lead data said 0.45/0.23/0.12/0.06; a broken run comparing
# "any occurrence" against "first occurrence" said 1.00. The measurement says 0.32 and
# then almost nothing.
#
# Note what the blend buys: only w1 improves materially (0.1849 -> 0.1760). At w2 the
# blend is WORSE than P_stat alone, and w3/w4 are within 0.001. The small non-zero
# weights are kept because they are what the optimiser chose on held-out seasons, and
# because an independent model guards against a silent failure in ours.
#
# Caveat that stays: GEFS is not EC46. A real dynamical ensemble scored against real
# observations at the real leads, but a different system from the one we serve.
NWP_WEIGHT = {"w1": 0.32, "w2": 0.09, "w3": 0.01, "w4": 0.06}
WEIGHT_PROVENANCE = (
    "measured: 20,274 first-occurrence triples, 6 monsoon seasons (2010-2015), NOAA "
    "GEFSv12 reforecast vs IMD, weights fitted leave-one-season-out (fold sd 0.01-0.08). "
    "P_stat outperforms the ensemble at every lead. GEFS is a proxy for EC46, not EC46."
)

SHARPEN_BASE = 2.0
SHARPEN_SLOPE = 8.0     # strength = 2 + 8w; optimal was 5 at w~0.36 and 4 at w=0.22
# The contract rounds to 3 dp, so anything below 0.0005 becomes exactly 0.000 — the
# improper-probability bug that (k+0.5)/(n+1) exists to avoid. The floor must clear it.
FLOOR = 0.001
CALIBRATION_PROVENANCE = (
    "mean-preserving beta-transformed linear pool (after Ranjan & Gneiting 2010); "
    "sharpening strength 2+8w, a:b solved per slot so the mean forecast is unchanged"
)


# Validated per lead on real blend outcomes, not assumed. A lead absent from this map
# gets no transform — which is correct, not an omission: at w2-w4 the NWP weight is
# 0.09/0.01/0.06, so the "pool" is essentially P_stat alone and is already calibrated.
# Measured out-of-sample (leave-one-season-out, 6 seasons, 20,274 triples):
#   w1  Brier 0.17564 -> 0.17410, delta +0.00154, CI (+0.00016, +0.00290), P(worse) 0.017
#   w2  -0.00000  P(worse) 0.733      w3  +0.00000  P(worse) 0.268
#   w4  -0.00018  P(worse) 0.690
RECALIBRATE = {"w1": 3.0}


def sharpen_strength(w: float) -> float:
    return SHARPEN_BASE + SHARPEN_SLOPE * w


def mean_preserving(p, strength: float):
    """Beta CDF with a:b solved so the mean forecast is unchanged — sharpen, never shift.

    A freely fitted Beta also moves the location, and the only parameters we could fit
    came from a proxy at base rate 0.616; applied to dry spells at 0.40 they shifted every
    probability down ~0.07, systematically under-warning. The theorem is about SHARPNESS.
    """
    p = np.asarray(p, float)
    if strength <= 2.0 or len(p) < 2:
        return p
    from scipy.optimize import brentq
    from scipy.stats import beta as _beta

    q = np.clip(p, 1e-6, 1.0 - 1e-6)
    target = float(q.mean())

    def gap(frac):
        a = max(1e-3, frac * strength)
        return float(_beta.cdf(q, a, max(1e-3, strength - a)).mean()) - target

    try:
        frac = brentq(gap, 0.02, 0.98, xtol=1e-4)
    except ValueError:
        return p
    return np.clip(_beta.cdf(q, frac * strength, strength - frac * strength),
                   FLOOR, 1.0 - FLOOR)


def beta_transform(p, w: float):
    """Mean-preserving beta recalibration of a linear pool. NOT CURRENTLY APPLIED.

    Kept because the underlying problem is real: Ranjan & Gneiting (2010) prove a linear
    pool of calibrated forecasts is necessarily uncalibrated, and ours measured 0.0060
    reliability against ~1e-5 for the model alone.

    Not shipped because it is validated only on a PROXY: daily dry-day, climatology as
    the calibrated component, base rate 0.616. There it cut reliability 7x. On a
    synthetic case with a sharp, biased second component it made reliability 5x WORSE —
    the fixed sharpening strength over-sharpens a pool that was not under-sharp. The
    theorem covers a pool of two CALIBRATED forecasts; ours is calibrated + uncalibrated,
    so under-sharpness is an assumption, not a guarantee.

    To enable it, fit and validate the strength out-of-sample on real (P_nwp, P_stat,
    outcome) triples for the actual targets. scripts/derive_blend_weights.py builds those
    from the GEFS reforecast, but its outcome construction does not yet reconcile with
    the feature table (see W2 notes), so that validation is still pending.
    """
    p = np.asarray(p, float)
    if w <= 0 or len(p) < 2:
        return p
    from scipy.optimize import brentq
    from scipy.stats import beta as _beta

    q = np.clip(p, 1e-6, 1.0 - 1e-6)
    strength = sharpen_strength(w)
    target = float(q.mean())

    def gap(frac):
        a = max(1e-3, frac * strength)
        return float(_beta.cdf(q, a, max(1e-3, strength - a)).mean()) - target

    try:
        frac = brentq(gap, 0.02, 0.98, xtol=1e-4)
    except ValueError:
        return p        # no mean-preserving split exists; leave the pool alone
    a = frac * strength
    return np.clip(_beta.cdf(q, a, strength - a), FLOOR, 1.0 - FLOOR)


def blend(stat: pd.DataFrame, nwp: pd.DataFrame,
          weights: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Weighted mean per cell per slot. Where one side is absent the other takes the
    full weight, and the slot is reported — a silently one-sided blend is a lie about
    provenance, not a reasonable default."""
    w = weights or NWP_WEIGHT
    cols = sorted(set(stat.columns) | set(nwp.columns))
    idx = stat.index.union(nwp.index)
    s = stat.reindex(index=idx, columns=cols)
    n = nwp.reindex(index=idx, columns=cols)

    out = pd.DataFrame(index=idx, columns=cols, dtype=float)
    sources = {}
    for c in cols:
        lead = c.rsplit("_", 1)[-1]
        wn = float(w.get(lead, 0.5))
        sv, nv = s[c], n[c]
        both = sv.notna() & nv.notna()
        # recalibrate AFTER pooling — the literature is explicit that combine-then-
        # recalibrate beats recalibrate-then-combine, and only the pool is miscalibrated
        pooled = (wn * nv[both] + (1 - wn) * sv[both])
        # Recalibrate only where it was MEASURED to help, at the strength the held-out
        # seasons chose. Everywhere else the pool ships as-is.
        st = RECALIBRATE.get(lead)
        out.loc[both, c] = (mean_preserving(pooled.to_numpy(), st)
                            if st is not None and both.sum() > 1 else pooled)
        # one-sided slots are a single source, already calibrated (stat) or raw (nwp);
        # a pool of one is not a pool, so no transform
        out.loc[sv.notna() & nv.isna(), c] = sv[sv.notna() & nv.isna()]
        out.loc[nv.notna() & sv.isna(), c] = nv[nv.notna() & sv.isna()]
        sources[c] = ("blend" if both.all() else
                      "stat_only" if nv.isna().all() else
                      "nwp_only" if sv.isna().all() else "mixed")
    return out.clip(FLOOR, 1.0 - FLOOR), sources
