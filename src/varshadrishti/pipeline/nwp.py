"""Ensemble member fractions -> P_nwp, one probability per cell per event per lead week.

An ensemble already IS a probability forecast: if 12 of 51 members produce a 7-day dry
spell in week 3, that is 24%. No model is fitted here and none should be - fitting a
post-processor would need a hindcast archive we do not have (see verify_nwp.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..features import labels as L

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "cache"

LEADS = {"w1": (1, 7), "w2": (8, 14), "w3": (15, 21), "w4": (22, 28)}
EVENTS = ("p_dry7", "p_dry14", "p_heavy", "p_onset", "p_false_onset")


def _member_fraction(hits: int, n: int) -> float:
    """(k + 0.5) / (n + 1), not k / n.

    0 of 81 members does not mean the event is impossible; it means p is below roughly
    1/81. A raw fraction publishes 0.000 and 1.000, which no proper score forgives and no
    forecaster should claim. This is the usual Laplace-style adjustment and it keeps every
    published probability strictly inside (0, 1).
    """
    return (hits + 0.5) / (n + 1.0)


def load_run(model: str, as_of: str) -> dict:
    p = CACHE / model / f"{as_of}.json"
    if not p.exists():
        raise FileNotFoundError(f"no cached {model} run for {as_of} — run scripts/fetch_nwp.py")
    return json.loads(p.read_text())


def _member_matrix(cell: dict) -> tuple[np.ndarray, pd.DatetimeIndex]:
    """-> (n_members+1, n_days) including the control, and the valid dates."""
    rows = [cell["control"]] + list(cell["members"])
    arr = np.array([[np.nan if v is None else float(v) for v in r] for r in rows], float)
    return arr, pd.to_datetime(cell["time"])


def _events_for_member(x: np.ndarray, onset_bar: float) -> dict:
    """Which events does this single member's rainfall trace produce, per day?"""
    dry = x < L.RAINY_DAY_MM
    n = len(x)

    def run_starts(days: int) -> np.ndarray:
        out = np.zeros(n, bool)
        if n >= days:
            c = np.convolve(dry.astype(float), np.ones(days), mode="valid")
            out[: len(c)] = c >= days
        return out

    five = np.convolve(np.nan_to_num(x), np.ones(L.WET_WINDOW_DAYS), mode="valid")
    rainy5 = np.convolve((x >= L.RAINY_DAY_MM).astype(float),
                         np.ones(L.WET_WINDOW_DAYS), mode="valid")
    cand = np.zeros(n, bool)
    ok = (five >= onset_bar) & (rainy5 >= L.WET_WINDOW_RAINY)
    cand[L.WET_WINDOW_DAYS - 1: L.WET_WINDOW_DAYS - 1 + len(ok)] = ok

    return {
        "p_dry7": run_starts(L.DRY_SPELL_DAYS),
        "p_dry14": run_starts(14),
        "p_heavy": x >= L.HEAVY_MM,
        "p_onset": cand,
        # a candidate that a 10-day near-dry window follows inside 30 days
        "p_false_onset": cand & _false_mask(x, cand),
    }


def _false_mask(x: np.ndarray, cand: np.ndarray) -> np.ndarray:
    out = np.zeros(len(x), bool)
    for i in np.flatnonzero(cand):
        after = np.nan_to_num(x[i + 1: i + 1 + L.FALSE_CHECK_DAYS])
        if len(after) >= L.FALSE_DRY_DAYS:
            c = np.convolve(after, np.ones(L.FALSE_DRY_DAYS), mode="valid")
            out[i] = bool((c < L.FALSE_DRY_MM).any())
    return out


def probabilities(model: str, as_of: str, onset_bar: pd.Series) -> pd.DataFrame:
    """-> DataFrame indexed by cell_id, columns '<event>_<lead>' in [0,1].

    A cell's probability for a lead week is the fraction of members in which the event
    occurs anywhere inside that week's days.
    """
    run = load_run(model, as_of)
    start = pd.Timestamp(as_of)
    rows = {}

    for cell_id, cell in run["cells"].items():
        arr, dates = _member_matrix(cell)
        offs = (dates - start).days.to_numpy()
        bar = float(onset_bar.get(cell_id, L.ONSET_FLOOR_MM))

        per_member = [_events_for_member(arr[m], bar) for m in range(arr.shape[0])]
        out = {}
        for ev in EVENTS:
            stack = np.vstack([pm[ev] for pm in per_member])        # members x days
            for lead, (a, b) in LEADS.items():
                win = (offs >= a) & (offs <= b)
                if not win.any():
                    out[f"{ev}_{lead}"] = np.nan
                    continue
                # FIRST occurrence, not any occurrence — this must match P_stat.
                #
                # P_stat comes from cumulative targets differenced: P(within k weeks) -
                # P(within k-1). Because several dry spells can start in different
                # sub-windows those events are NOT disjoint, so the difference is
                # "the FIRST spell starts in week k", not "a spell starts in week k".
                # Measured over 2010-2015: days 1-7 = 0.363, days 8-14 = 0.389,
                # days 1-14 = 0.536, so P(both) = 0.216 — far from zero. Taking "any
                # occurrence" here would blend two different events, which is the bug
                # this replaces.
                earlier = offs < a
                first = stack[:, win].any(axis=1)
                if earlier.any():
                    first &= ~stack[:, earlier].any(axis=1)
                out[f"{ev}_{lead}"] = _member_fraction(int(first.sum()), stack.shape[0])
        rows[cell_id] = out

    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "cell_id"
    return df


def horizon_days(model: str, as_of: str) -> int:
    run = load_run(model, as_of)
    any_cell = next(iter(run["cells"].values()))
    return len(any_cell["time"])
