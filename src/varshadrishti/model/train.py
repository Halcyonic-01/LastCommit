"""Leave-one-year-out training, nested isotonic calibration, skill against climatology.

The whole file exists to answer one question honestly: does this beat knowing the local
climate? Three rules make the answer trustworthy, and each is pinned by a test.

  SPLIT BY YEAR.  1.34 M rows but only 34 independent seasons. Neighbouring cells on the
  same day are one weather event; a random split leaks and returns a fake 95%.
  EARLY STOPPING SEES WHOLE YEARS TOO, drawn from inside the training set, never the
  held-out one - otherwise the stopping iteration is tuned on the test year.
  CALIBRATION IS ALSO OUT-OF-FOLD. An isotonic map fitted on all out-of-fold predictions
  and then scored on those same predictions flatters itself.

One channel is NOT closed, and it should be said out loud rather than discovered. P4's
climatology features are leave-one-year-out per row: a 1995 row carries climatology from
every season but 1995 - which includes the season being held out here. So a training row
has seen ~1/33 of the test year, smoothed over 15 days. The bound is small and the usual
practice in this literature is a full-record climatological covariate, but it is a real
channel. Closing it properly means recomputing P4's climatology inside each fold.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

TARGETS = [
    "y_onset_7", "y_onset_14", "y_onset_21", "y_onset_28",
    "y_dry7_7", "y_dry7_14", "y_dry7_21", "y_dry7_28", "y_dry14_7", "y_dry14_14",
    "y_heavy_7",
]

NON_FEATURES = {"date", "cell_id", "year", "sday"}

# P5b: these take ~5 values a season (80-88% of their variance is between-year), so with
# 34 seasons a split on them is close to a split on "which year is this". Dropping them
# improved paired BSS on all three headline targets - P(worse) 0.005 and 0.001 on onset
# and heavy rain. Do not reinstate without a paired test that clears zero.
EXCLUDED = {"oni", "dmi", "nino34_anom"}

# Deliberately small. With 34 independent seasons, capacity buys memorisation, not skill.
# P5b: heavier bagging. min_child_samples counts ROWS and one season is ~39k rows, so it
# never constrained year-level memorisation; subsampling does. +0.006 BSS and 22 -> 25
# positive seasons on the dry spell.
PARAMS = dict(
    objective="binary", learning_rate=0.05, num_leaves=31, min_child_samples=200,
    subsample=0.6, subsample_freq=1, colsample_bytree=0.6,
    reg_lambda=1.0, n_estimators=600, verbose=-1, n_jobs=-1,
)
EARLY_STOP = 40
INNER_VAL_YEARS = 3
CLIM_WINDOW = 7  # +/- days smoothing, so each climatology bin rests on ~500 observations


def feature_names(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns
            if c not in NON_FEATURES and c not in EXCLUDED and not c.startswith("y_")]


def _inner_val_years(train_years: list[int], fold: int) -> list[int]:
    """Whole years held out of training for early stopping, spread across the record.

    Scaled to the record: taking a flat 3 out of a 5-year training set leaves 2 years to
    fit on, and the model loses to climatology for want of data rather than for cause.
    """
    k = max(1, min(INNER_VAL_YEARS, len(train_years) // 4))
    step = max(1, len(train_years) // k)
    picked = [train_years[(fold + i * step) % len(train_years)] for i in range(k)]
    return sorted(set(picked))


def climatology_reference(df: pd.DataFrame, target: str, years: list[int]) -> pd.Series:
    """Per (cell, day-of-season) base rate of the target, leave-one-year-out and smoothed.

    The reference has to be held out too. Fitted on all 34 seasons it would have seen the
    year it is being scored on, which makes the bar we are clearing an unfair one.
    """
    tab = (df.groupby(["year", "cell_id", "sday"])[target].mean()
             .rename("v").reset_index())
    tot = tab.pivot_table(index="sday", columns="cell_id", values="v", aggfunc="sum")
    cnt = tab.pivot_table(index="sday", columns="cell_id", values="v", aggfunc="count")

    out = pd.Series(np.nan, index=df.index, dtype=float)
    for y in years:
        yt = tab[tab.year == y].pivot_table(index="sday", columns="cell_id", values="v", aggfunc="sum")
        yc = tab[tab.year == y].pivot_table(index="sday", columns="cell_id", values="v", aggfunc="count")
        num = (tot - yt.reindex_like(tot).fillna(0))
        den = (cnt - yc.reindex_like(cnt).fillna(0))
        # smooth across neighbouring days of the season, centred and symmetric
        w = 2 * CLIM_WINDOW + 1
        num = num.rolling(w, center=True, min_periods=1).sum()
        den = den.rolling(w, center=True, min_periods=1).sum()
        rate = (num / den.replace(0, np.nan))

        m = df.year == y
        sub = df.loc[m, ["cell_id", "sday"]]
        vals = rate.to_numpy()[
            rate.index.get_indexer(sub["sday"]), rate.columns.get_indexer(sub["cell_id"])
        ]
        out.loc[m] = vals
    return out.fillna(df[target].mean())


def shuffled_labels(df: pd.DataFrame, target: str, years: list[int], seed: int = 0) -> np.ndarray:
    """Labels shuffled WITHIN each season: seasonal base rates survive, row signal does not.

    Whatever consumes this must also rebuild the climatology reference from it. Scoring a
    shuffled-label model against the real labels' climatology compares two different
    worlds, and the model wins for free.
    """
    rng = np.random.default_rng(seed)
    y = df[target].to_numpy(float).copy()
    for yr in years:
        m = (df.year == yr).to_numpy()
        v = y[m]
        rng.shuffle(v)
        y[m] = v
    return y


def loyo_predict(df: pd.DataFrame, target: str, feats: list[str], years: list[int],
                 params: dict | None = None, shuffle_labels: bool = False,
                 seed: int = 0, progress=None) -> tuple[pd.Series, list[dict]]:
    """Out-of-fold probabilities: every row scored by a model that never saw its year."""
    import lightgbm as lgb

    params = {**PARAMS, **(params or {})}
    oof = pd.Series(np.nan, index=df.index, dtype=float)
    info = []

    y_all = shuffled_labels(df, target, years, seed) if shuffle_labels else df[target].to_numpy(float)

    for fold, hold in enumerate(years):
        tr_years = [y for y in years if y != hold]
        val_years = _inner_val_years(tr_years, fold)
        fit_years = [y for y in tr_years if y not in val_years]

        fit_m = df.year.isin(fit_years).to_numpy()
        val_m = df.year.isin(val_years).to_numpy()
        te_m = (df.year == hold).to_numpy()

        model = lgb.LGBMClassifier(**params)
        model.fit(
            df.loc[fit_m, feats], y_all[fit_m],
            eval_X=df.loc[val_m, feats], eval_y=y_all[val_m],
            eval_metric="binary_logloss",
            callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)],
        )
        oof.loc[te_m] = model.predict_proba(df.loc[te_m, feats])[:, 1]
        info.append({"year": hold, "best_iter": int(model.best_iteration_ or params["n_estimators"]),
                     "n_fit": int(fit_m.sum())})
        if progress:
            progress(f"    {target} {hold} iter={info[-1]['best_iter']}")
    return oof, info


def calibrate_oof(oof: pd.Series, y: pd.Series, years_col: pd.Series,
                  years: list[int]) -> pd.Series:
    """Isotonic, itself leave-one-year-out, so the calibrated numbers stay honest."""
    out = pd.Series(np.nan, index=oof.index, dtype=float)
    for hold in years:
        m = (years_col == hold).to_numpy()
        fit = ~m & oof.notna().to_numpy()
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(oof[fit], y[fit])
        out.loc[m] = iso.predict(oof[m])
    return out
