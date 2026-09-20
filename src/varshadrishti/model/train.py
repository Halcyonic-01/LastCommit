"""The target and feature contract shared by training and serving.

Training itself lives in the separate varsha-drishti-model repo, which fits the XGBoost
boosters vendored into models/xgb. What stays here is the vocabulary the rest of this
project reads: which targets the contract publishes, and which columns are predictors.
"""

from __future__ import annotations

import pandas as pd

# 5 events x 4 leads = exactly the 20 probabilities the frozen contract publishes.
# Anything absent here is a value the app would otherwise have to invent.
TARGETS = ([f"y_{e}_{h}" for e in ("onset", "false_onset", "dry7", "dry14", "heavy")
            for h in (7, 14, 21, 28)])

NON_FEATURES = {"date", "cell_id", "year", "sday"}

# P5b: these take ~5 values a season (80-88% of their variance is between-year), so with
# 34 seasons a split on them is close to a split on "which year is this". Dropping them
# improved paired BSS on all three headline targets - P(worse) 0.005 and 0.001 on onset
# and heavy rain. Measured again on the current data: oni 85.2%, nino34_anom 83.5%,
# dmi 77.4% between-year. Do not reinstate without a paired test that clears zero.
#
# W6 then asked whether ANY representation of ENSO/IOD is learnable here, since PS 26086
# mandates them as inputs, and closed the question: no. ENSO-conditioned climatology lost
# -0.0129/-0.0125/-0.0134 BSS, and the real ENSO grouping was statistically
# indistinguishable from a shuffled one (p=0.63/0.13/0.87), improving only 7-10 of 34
# seasons where a coin flip gives 17. Root cause: 34 seasons hold ~6 El Nino and ~6 La
# Nina, so any phase-conditioned statistic is dominated by sampling error. Adding rows on
# the (cell x season-day) axes raises the row count but not the season count, and seasons
# are the independent unit. Three representations, three failures, one cause. ENSO/IOD are
# therefore ingested and published as context only (provenance.teleconnection, flagged
# is_forecast: false) - tested and rejected on evidence, not dropped by assumption.
EXCLUDED = {"oni", "dmi", "nino34_anom"}


def feature_names(df: pd.DataFrame) -> list[str]:
    """Predictor columns in `df`: everything that is not an id, a target, or excluded."""
    return [c for c in df.columns
            if c not in NON_FEATURES and c not in EXCLUDED and not c.startswith("y_")]
