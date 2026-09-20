# VarshaDrishti monsoon event models

20 binary XGBoost classifiers (onset, false onset, 7-day dry spell, 14-day dry
spell/break, heavy rain — each at 7/14/21/28-day lead) plus a 4-week onset
hazard model, trained on IMD gridded rainfall for Karnataka (323 cells,
1991–2024, June–September). Chronological split: train 1991–2015, validation
2016–2019, test 2020–2024 (held out throughout development).

## Install

```bash
pip install xgboost pandas numpy
```

Nothing else — this folder is self-contained, no dependency on the training
repo.

## Quick start

```python
from predict import EventModel, onset_survival_curve

model = EventModel.load("events/onset_21d")

row = {
    "rain_1d": 12.4, "rain_3d": 28.0, "rain_7d": 61.2, ...
    # see events/onset_21d/features.json for the full required list
}
prob = model.predict_proba(row)          # P(onset within 21 days), as a probability
call = model.predict(row)                # binary call, using this model's own tuned threshold

# The richer onset output -- see "Which onset output to use" below:
curve = onset_survival_curve("onset_hazard", row)
```

Any field you don't have can simply be left out of `row` — XGBoost handles
missing values natively. This matters most for the `ecmwf_*` fields (see
below).

## Directory layout

```
events/<event>_<horizon>d/     20 models, e.g. events/heavy_14d/
onset_hazard/week{1,2,3,4}/    4-week discrete-time onset hazard model
  model.json                   the trained booster
  features.json                exact ordered list of features this model expects
  metadata.json                decision_threshold, hyperparameters, training provenance
  metrics.json                 held-out test performance (ROC-AUC, PR-AUC, Brier skill, etc.)
  importances.csv              feature importance (gain/weight/cover)
predict.py                     inference helper (only file you need to import)
```

## Which onset output to use

Two ways to get an onset forecast, and they answer different questions:

- **`events/onset_{7,14,21,28}d`** — "will onset occur within N days" (cumulative). Simple, matches the other event families' interface. At 28 days this is 85% positive by construction, so read the probability, not just a threshold call.
- **`onset_survival_curve()`** — "which week does onset happen in" (conditional hazard, chained into a proper survival curve). More informative, and the honest picture of where skill actually lives: week 1 is reliably forecastable (AUC 0.78), skill drops off sharply after that, and **week 4 (`hazard_week4_reliable: False` in the output) is close to random (AUC 0.55) — treat it as low-confidence, not a real signal.**

## Feature families (see each model's `features.json` for its exact list)

- **Rainfall/spell state**: `rain_1d/3d/7d/14d/30d`, `wet_days_30d`, `days_since_rain`, `wet_spell_today`, `wet_spell_seen`, `days_since_wet_spell`, `spell_deficit`, `reg_rain_7d`, `reg_dry`, `rain_7d_vs_region`, `doy`
- **Climatology** (`clim_*`, `onset_doy_anom`): per-cell, day-of-season statistics computed from 1991–2015 only (no test-year leakage)
- **MJO/circulation** (`mjo_*`, `rmm1/2`, and the `llj_u850`/`wf_shear`/`wy_shear`/`v850_bob`/`trough_slp`/`tt_grad`/`olr_*` families): large-scale monsoon circulation indices
- **`mjo_cos_valid_{H}d` / `mjo_sin_valid_{H}d`**: only in the horizon-`H` model, extrapolated MJO phase at that specific lead
- **`ecmwf_mean_mm_{7,14,21,28}d` / `ecmwf_std_mm_{7,14,21,28}d`**: ensemble mean/spread of ECMWF S2S reforecast rainfall. **Only present in the `onset` models and hazard weeks 1–3** — proven by ablation to help there specifically, proven not to help the other 4 event families, so it isn't in those models at all. Sparse by nature (real ECMWF cycle dates only, ~2004–2023 coverage); leave these fields out of `row` if you don't have this data source, predictions still work.

## Model quality summary (test years 2020–2024)

| Family | ROC-AUC range (7→28d) | Verdict |
|---|---|---|
| Onset | 0.76 – 0.87 | Strong, most rigorously validated (fair-baseline + year-blocked bootstrap tested) |
| Heavy rain | 0.79 – 0.88 | Strong |
| 7-day dry spell | 0.74 – 0.77 | Good |
| False onset | 0.68 – 0.75 | Fair |
| 14-day dry spell (break) | 0.67 – 0.76 | Weak — barely beats climatology; six independent fixes attempted, this is a genuine ceiling with current data |

Full metrics for every model are in its own `metrics.json`.
