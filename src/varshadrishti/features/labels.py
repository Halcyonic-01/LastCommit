"""Onset, false onset, dry spell and heavy rain, per cell per season.

Onset follows Moron & Robertson: the first 5-day wet sequence that clears a local
sowing-rain bar, kept only if no 10-day near-dry window follows within 30 days.

Two adaptations to Karnataka, both measured rather than assumed:

  THE BAR IS AGRONOMIC, NOT CLIMATOLOGICAL. M-R phrase it as the local climatological
  wet spell. Read as the local MEAN that is ~390 mm in a Western Ghats cell, which would
  mean the monsoon never arrives there. Germination is physical - about 20-25 mm for ragi
  and groundnut - so the bar is a low quantile of the local wet spells held in a 20-40 mm
  band: locality shifts it, it does not scale with a cell's rainfall.

  THE KILL RULE STAYS FLAT AT 5 mm. Localising it was tried and is wrong in both
  directions - see the P4 notes. In the rain shadow a 10-day <5 mm window occurs ~50x a
  season, so ~40% of those cell-seasons never produce a CONFIRMED onset. That is the
  finding, not a defect: it is why `first_cand_doy` exists alongside `onset_doy`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --- agronomic constants, sourced not invented -----------------------------
RAINY_DAY_MM = 2.5      # IMD rainy day; also the Karnataka dry-zone "threshold dry day"
WET_WINDOW_DAYS = 5     # germination needs a sustained spell, not one burst
WET_WINDOW_RAINY = 3    # at least 3 of those 5 days must actually rain
ONSET_FLOOR_MM = 20.0   # S. Karnataka dry-farming threshold rainfall for ragi/groundnut
ONSET_CAP_MM = 40.0     # above this we are describing local climate, not germination
WET_SPELL_Q = 0.20      # the modest end of the local wet-spell range, not its mean
FALSE_DRY_DAYS = 10     # Moron-Robertson kill window
FALSE_DRY_MM = 5.0      # ...as a TOTAL over those 10 days, not a per-day rate
FALSE_CHECK_DAYS = 30   # how long after onset the crop is still vulnerable
DRY_SPELL_DAYS = 7      # CRIDA break; 14-day variant is the severe one
HEAVY_MM = 64.5         # IMD "heavy rainfall" day

SEASON_START_MD = (6, 1)    # searching from 1 Jun keeps this a MONSOON onset
SEASON_END_MD = (9, 30)
ONSET_LAST_MD = (8, 31)     # a first onset in September is a withdrawal artefact
CONFIRM_END_MD = (10, 31)   # ...but the 30-day confirmation may look past the season


def _season_slice(rain: pd.DataFrame, year: int) -> pd.DataFrame:
    a = pd.Timestamp(year, *SEASON_START_MD)
    b = pd.Timestamp(year, *SEASON_END_MD)
    return rain.loc[a:b]


def wet_spell_threshold(rain: pd.DataFrame, years) -> pd.Series:
    """Per cell: the local bar a 5-day spell must clear to count as a sowing rain.

    A LOW quantile of the local wet-spell distribution, held inside an agronomic band.
    The mean is the wrong statistic: in a Western Ghats cell it is ~390 mm, which would
    mean the monsoon never arrives there. Germination is physical - roughly 20-25 mm for
    ragi and groundnut - and locality shifts that a little, not by a factor of fifteen.
    """
    parts = []
    for y in years:
        s = _season_slice(rain, y)
        if s.empty:
            continue
        five = s.rolling(WET_WINDOW_DAYS).sum()
        rainy = (s >= RAINY_DAY_MM).rolling(WET_WINDOW_DAYS).sum()
        parts.append(five.where(rainy >= WET_WINDOW_RAINY))  # conditioned on wet, per M-R
    wet = pd.concat(parts)
    q = wet.quantile(WET_SPELL_Q).fillna(ONSET_FLOOR_MM)
    return q.clip(lower=ONSET_FLOOR_MM, upper=ONSET_CAP_MM)


def _first_dry_run(x: np.ndarray, days: int, total_mm: float):
    """Index of the first `days`-long window accumulating less than `total_mm`, else None."""
    if len(x) < days:
        return None
    c = np.convolve(np.nan_to_num(x), np.ones(days), mode="valid")
    hit = np.where(c < total_mm)[0]
    return int(hit[0]) if len(hit) else None


def onset_for_cell(daily: np.ndarray, thresh: float, last_candidate: int | None = None,
                   kill_mm: float = FALSE_DRY_MM):
    """-> (onset_idx, [false_onset_idx...]). Indices are offsets into the season array."""
    x = np.nan_to_num(daily)
    cutoff = len(x) if last_candidate is None else last_candidate
    five = np.convolve(x, np.ones(WET_WINDOW_DAYS), mode="valid")
    rainy = np.convolve((x >= RAINY_DAY_MM).astype(float), np.ones(WET_WINDOW_DAYS), mode="valid")
    candidates = np.where((five >= thresh) & (rainy >= WET_WINDOW_RAINY))[0]
    candidates = candidates[candidates <= cutoff]

    false_starts = []
    resume = 0  # one burst spans 5 overlapping windows; count the EVENT, not the windows
    for i in candidates:
        if i < resume:
            continue
        after = x[i + WET_WINDOW_DAYS : i + WET_WINDOW_DAYS + FALSE_CHECK_DAYS]
        # too close to the season end to judge - treat as unconfirmed, not as a false start
        if len(after) < FALSE_DRY_DAYS:
            return (int(i), false_starts)
        dry_at = _first_dry_run(after, FALSE_DRY_DAYS, kill_mm)
        if dry_at is None:
            return (int(i), false_starts)
        false_starts.append(int(i))
        # nothing can genuinely start inside the dry spell that just killed this one
        resume = i + WET_WINDOW_DAYS + dry_at + FALSE_DRY_DAYS
    return (None, false_starts)


def season_labels(rain: pd.DataFrame, year: int, thresh: pd.Series,
                  kill: pd.Series | None = None) -> pd.DataFrame:
    """One row per cell for `year`: onset date, false-start count, and their day-of-year.

    Candidates are sought in Jun-Aug; confirmation may read into October, so a late-August
    onset is judged on real rain rather than on the season slice running out.
    """
    s = rain.loc[pd.Timestamp(year, *SEASON_START_MD):pd.Timestamp(year, *CONFIRM_END_MD)]
    last_cand = (pd.Timestamp(year, *ONSET_LAST_MD) - pd.Timestamp(year, *SEASON_START_MD)).days
    dates = s.index
    rows = []
    for cell in s.columns:
        km = FALSE_DRY_MM if kill is None else float(kill[cell])
        onset_i, false_i = onset_for_cell(s[cell].to_numpy(), float(thresh[cell]), last_cand, km)
        # The first candidate is the rain the farmer actually sows on, confirmed or not.
        # In the rain shadow a CONFIRMED onset often never comes, so the strict label is
        # missing ~40% of the time there - that column would be useless as climatology.
        first_i = false_i[0] if false_i else onset_i
        rows.append({
            "year": year,
            "cell_id": cell,
            "onset_date": dates[onset_i] if onset_i is not None else pd.NaT,
            "onset_doy": int(dates[onset_i].dayofyear) if onset_i is not None else np.nan,
            "first_cand_doy": int(dates[first_i].dayofyear) if first_i is not None else np.nan,
            "first_cand_failed": bool(false_i),
            "n_false_starts": len(false_i),
            "first_false_doy": int(dates[false_i[0]].dayofyear) if false_i else np.nan,
        })
    return pd.DataFrame(rows)


PHASES = ("pre_onset", "resow", "in_season")


def onset_phase(rows: pd.DataFrame, onset: pd.DataFrame) -> np.ndarray:
    """Which onset question is live per row: pre_onset (sow), resow, in_season (answered).

    Pooling them lets persistence carry the score - 51% of cell-days are in_season, where
    consecutive 5-day windows overlap and BSS is 2.4x the pre-onset one.
    """
    if "wet_spell_seen" not in rows:
        raise KeyError("onset_phase needs the causal wet_spell_seen column")
    o = rows[["year", "cell_id"]].merge(onset[["year", "cell_id", "onset_doy"]],
                                        on=["year", "cell_id"], how="left")
    # onset_doy is the spell's START; wet_spell_seen fires when it CLOSES, four days later
    confirmed = o["onset_doy"].to_numpy(float) + (WET_WINDOW_DAYS - 1)
    seen = rows["wet_spell_seen"].to_numpy() == 1
    # in_season needs 30 days of hindsight, so only pre_onset is separable at forecast time
    past = seen & np.isfinite(confirmed) & (rows["doy"].to_numpy(float) >= confirmed)
    return np.where(~seen, "pre_onset", np.where(past, "in_season", "resow"))


def daily_event_labels(rain: pd.DataFrame, thresh: pd.Series | None = None) -> dict[str, pd.DataFrame]:
    """Forward-looking event flags. These are TARGETS - never feed one back as a feature."""
    dry = rain < RAINY_DAY_MM

    def dry_run_ahead(days: int) -> pd.DataFrame:
        # a run STARTING today: reverse-rolling sum of dry days over the next `days`
        fwd = dry[::-1].rolling(days, min_periods=days).sum()[::-1]
        return (fwd >= days).fillna(False)

    # a sowing rain that a 10-day near-dry window then kills — the headline label, and
    # until now the one event the contract carried with no model behind it
    five = rain.rolling(WET_WINDOW_DAYS).sum()
    rainy5 = (rain >= RAINY_DAY_MM).rolling(WET_WINDOW_DAYS).sum()
    cand = (five.ge(thresh, axis=1) & (rainy5 >= WET_WINDOW_RAINY)).fillna(False) \
        if thresh is not None else pd.DataFrame(False, index=rain.index, columns=rain.columns)
    fwd_dry = dry[::-1].rolling(FALSE_DRY_DAYS, min_periods=FALSE_DRY_DAYS).sum()[::-1]
    kills = (fwd_dry >= FALSE_DRY_DAYS)
    kill_soon = kills[::-1].rolling(FALSE_CHECK_DAYS, min_periods=1).sum()[::-1] > 0

    return {
        "dry7_starts": dry_run_ahead(DRY_SPELL_DAYS),
        "dry14_starts": dry_run_ahead(14),
        "heavy": (rain >= HEAVY_MM).fillna(False),
        "false_onset_starts": (cand & kill_soon).fillna(False),
    }


def within_horizon(flag: pd.DataFrame, days: int) -> pd.DataFrame:
    """Does the event occur on any of the next `days` days - STRICTLY after today?

    Excluding today is not a detail. Include it and `y_onset_7` is 1 whenever the feature
    `wet_spell_today` is 1: P(target | feature) = 1.000, measured. The model then scores
    BSS +0.43 by reading the answer off its own input, and the forecast reduces to telling
    a farmer standing in the rain that it is raining.
    """
    fwd = flag[::-1].rolling(days, min_periods=1).sum()[::-1]
    ahead = fwd.shift(-1)  # drop today; the horizon is t+1 .. t+days
    return (ahead > 0).astype(float).where(ahead.notna())
