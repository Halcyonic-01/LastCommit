# VarshaDrishti

Hyperlocal monsoon **onset, false-onset and dry-spell** probability system at block and
panchayat scale. Karnataka pilot, national architecture.

SIH 2026 · PS 26086 · Ministry of Earth Sciences (MoES) / NCMRWF

> A farmer sows on a false onset just before a long pause and loses the crop to moisture
> stress. That case is our first-class output — we predict the *gap behind the rain*, not
> just the rain.

## What it does

ECMWF EC46 (51 members, 46 days) + an XGBoost model trained on 34 seasons of IMD rainfall
and ENSO/IOD/MJO indices → blended by lead time → probabilities of
onset, false onset, dry spell and heavy rain at 1–4 weeks → ICAR-CRIDA-cited crop advisories
→ delivered in Kannada by voice, WhatsApp and Telegram.

Scored with **Brier Skill Score against climatology**, never bare accuracy.

Runs on GitHub Actions and static JSON. **₹0/month.**

---

# First run

## 0. Prerequisites

| Need | Version | Check |
|---|---|---|
| Python | **3.12** | `python3.12 --version` |
| Node | 20+ | `node -v` |
| git | any | `git --version` |
| Free disk | **~2 GB** | raw data 1.0 GB · `.venv` 650 MB · `node_modules` 160 MB |

**Use 3.12.** The source compiles on 3.11–3.14, but 3.12 is what the pinned dependencies
(`imdlib==0.1.21`, geopandas, xgboost) are tested against here, and it is what CI will
use. If `python3` on your machine is something else, say `python3.12` explicitly below.

macOS: `brew install python@3.12 node`. Ubuntu: `sudo apt install python3.12 python3.12-venv nodejs npm`.

## 1. Install

```bash
git clone https://github.com/Halcyonic-01/LastCommit.git && cd LastCommit
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Every command below uses `.venv/bin/python` rather than an activated shell, so you can
copy-paste them into any terminal without worrying about which venv is live.

`.env` can stay empty for now. Nothing in the data pipeline, the model or the web app reads
it — only the Telegram sender does, and that is step 6.

## 2. What a fresh clone does *not* contain

Bulk data is gitignored on purpose: it is all re-downloadable, and a nightly job that
committed 1,127 files would make the history unusable. **You get this for free:**

```
geo/*.geojson                  Karnataka district / taluk / hobli boundaries
data/processed/weights_*.parquet   cell → area matrices (the expensive P2 output)
forecast/latest.json           a full mock forecast for all 1,127 areas
rules/                         the CRIDA advisory rules
```

**You have to build this:**

```
data/raw/*                     ~1.0 GB of rainfall, indices, boundaries
data/processed/features.parquet  the P5 training table
forecast/area/*.json           1,127 per-area files, regenerated from latest.json
```

Which means: **the web app runs immediately, the model pipeline needs step 4.**

## 3. Run the web app (2 minutes, no data download)

```bash
cd web && npm install
```

```bash
.venv/bin/python scripts/split_forecast.py
```

```bash
cd web && npm run dev
```

Open the printed URL (usually `http://localhost:5173`).

`split_forecast.py` explodes `forecast/latest.json` into the 1,127 per-area files the app
fetches. **`npm run dev` does not do this for you** — skip it and every screen shows a
load error. `npm run build` *does* run it automatically, via `scripts/prebuild.mjs`.

Six screens: `/` onboarding · `/today` the advisory · `/why` the explanation ·
`/rain` the farmer's rain report · `/officer` the map · `/verify` the honesty page.

## 4. Get the data (~1.0 GB, ~25 min)

Run these in order. Each is resumable — rerun after an interruption and it skips what is
already on disk.

```bash
.venv/bin/python scripts/download_imd.py       # 825 MB, ~13 min — 34 seasons, the training truth
.venv/bin/python scripts/download_indices.py   # 2.5 MB, seconds — ONI, Nino3.4, DMI, RMM MJO
.venv/bin/python scripts/download_boundaries.py  # 66 MB — KGIS Karnataka polygons
.venv/bin/python scripts/download_osm_names.py   # 28 KB — Kannada place names
.venv/bin/python scripts/download_crida.py     # 3.4 MB — 7 district contingency plans
.venv/bin/python scripts/download_chirps.py    # 83 MB, ~10 min — 0.05° panchayat layer
```

`download_chirps.py` is the **panchayat-scale** layer: 0.05° (~5.5 km) against IMD's 0.25°
(~27.5 km), so 12,880 Karnataka cells instead of ~300. It range-subsets the CHC server over
HTTP, so one season costs 2.7 MB and ~45 s rather than a 1 GB global file.

**Optional — the IMD fallback.** `scripts/download_era5_insurance.py` pulls ERA5-Land for
the same cells, used only if IMD Pune is unreachable. It is bounded by Open-Meteo's hourly
cap, not by our code, so it takes ~100 min wall-clock and must be run through its wrapper,
which restarts it after each cap:

```bash
./scripts/run_era5_until_done.sh
```

## 5. Build the pipeline

Order matters — each step reads the one before it.

```bash
.venv/bin/python scripts/build_geo.py          # boundaries → geo/*.geojson + weights_*.parquet
```

```bash
.venv/bin/python scripts/build_features.py     # IMD + indices → features.parquet (~1 min)
```

```bash
.venv/bin/python scripts/make_mock_forecast.py # → forecast/latest.json + index.json
```

```bash
.venv/bin/python scripts/split_forecast.py     # → forecast/area/*.json
```

`build_features.py` produces **1,339,804 rows × 39 columns, 53 MB** — 323 IMD cells ×
34 seasons × 122 days, with the onset / false-onset / dry-spell / heavy-rain labels and
the causal features the model trains on. See *Reading the feature table* below.

## 6. Telegram (optional)

Get a token from [@BotFather](https://t.me/BotFather), put it in `.env` as
`TELEGRAM_BOT_TOKEN`, then:

```bash
.venv/bin/python scripts/telegram_setup.py
```

It prints your chat id — paste that into `.env` as `TELEGRAM_CHAT_ID`. Then
`services/telegram/send.py` will deliver a real Kannada advisory to your phone.

## 7. WhatsApp (optional)

Create a Meta developer app with the WhatsApp product, add your own number as a
**verified recipient** in the App Dashboard's API Setup page, then put the phone
number id and access token in `.env` as `WHATSAPP_PHONE_NUMBER_ID` /
`WHATSAPP_ACCESS_TOKEN`. Verify it works:

```bash
.venv/bin/python scripts/whatsapp_setup.py --register <your verified number> --send
```

`--send` sends Meta's `hello_world` test template, which is always pre-approved —
useful to confirm delivery before any real advisory template is submitted for
approval. Once registered, `services/whatsapp/send.py` sends the same Kannada
advisory `services/telegram/send.py` does, but **only within 24h of that number
last messaging the bot** — outside that window WhatsApp requires a pre-approved
template (`--template NAME`), not free text. This is a platform rule, not a bug.

## 8. SMS (optional)

Create a [Twilio](https://www.twilio.com) account (trial is fine), put the Account
SID, Auth Token, and trial phone number in `.env`, verify a recipient number in the
Twilio console (Phone Numbers → Manage → Verified Caller IDs on a trial account),
then:

```bash
.venv/bin/python scripts/sms_setup.py --register +91XXXXXXXXXX --send
```

`services/sms/send.py` sends the same advisory text with Telegram/WhatsApp's
`*bold*`/`_italic_` markers stripped — SMS has no rich text, so left in they'd show
as literal punctuation. Kannada also forces UCS-2 encoding (67 chars/segment, not
160), so the full advisory is **~6 billed segments per message** — `--dry-run` prints
the exact count before you send anything for real.

Twilio numbers need a leading `+` (E.164); WhatsApp's numbers above must NOT have
one — the two APIs disagree on the format, so don't copy one field into the other.

**Never commit `.env`.** It is gitignored; keep it that way.

## 9. Test

```bash
.venv/bin/python -m pytest -q
```

| You should see | Meaning |
|---|---|
| `159 passed` | everything downloaded and built |
| `133 passed, 26 skipped` | fresh clone, no data yet — **this is correct**, not a failure |
| anything `failed` | a real problem; the assertion message says what |

Tests skip with the exact command that fixes them, so read the skip reasons rather than
guessing. The P3 web tests need `npm run build` in `web/` first; the P4 tests need
`build_features.py`.

---

# Reading the feature table

```python
import pandas as pd
df = pd.read_parquet("data/processed/features.parquet")
```

Two rules govern every column, and `tests/test_p4_features.py` enforces both by poking the
inputs rather than reading the source:

- **Causal** — a feature may only use rain up to and including that day. The *confirmed*
  onset date needs 30 days of hindsight, so it is a label and never a feature; the knowable
  wet-spell **candidate** (`wet_spell_seen`) is what the model gets.
- **Leave-one-year-out** — climatology for 1993 is built from the other 33 seasons. Fitted
  on all 34 it leaks the held-out year into its own prediction, and a shuffled-label test
  would not catch it.

**Split by year, never randomly.** Neighbouring cells in one season are the same weather
event; a random split leaks and produces a fake 95%. Every row carries `year` for this.

**Do not rebalance the classes.** Base rates are natural on purpose — resampling degrades
probability calibration, and Brier Skill Score is the metric. Weight or recalibrate instead.

---

# Using the trained model

The trained models are committed (`models/`, 3.5 MB), so **a teammate does not have to
train anything**. Clone, install, and they work. Training takes 45 minutes; loading takes
a second.

```bash
.venv/bin/python scripts/predict.py --date 2024-07-15 --limit 5
```

That prints a probability per area for all 20 targets. In your own code:

```python
from varshadrishti.model import predict_xgb as PX
PX.available()              # the 24 shipped models (20 events + 4 hazard weeks)
PX.predict(df, "y_dry7_7")  # one target, a probability per row
PX.predict_all(df)          # all 20 event targets
PX.onset_survival_curve(df) # per-week onset hazard + cumulative curve
```

`df` needs the feature columns. Build the base table once with `scripts/build_features.py`
(`data/processed/features.parquet` is NOT committed, 54 MB), then attach the circulation
and MJO predictors the boosters also expect:

```python
from varshadrishti.features import extended as EX
df = EX.attach(df)  # train-only climatology + 45 extended columns + ECMWF S2S
```

`EX.attach` is not optional. `features.parquet` ships `clim_*` as full-period 1991–2024
means, but the boosters were fitted on 1991–2015 only; scoring them on the shipped columns
leaks test-year information and silently overstates skill.

Inference needs only **xgboost, pandas and numpy**. There is no calibration step — the
boosters emit raw `binary:logistic` probabilities with a validation-tuned decision
threshold in each model's `metadata.json`.

**What the numbers mean.** Each is a probability between 0 and 1 for one area on one day —
`y_dry7_7` is "a 7-day dry spell begins within the next 7 days". They are calibrated, so
when the model says 0.45 the event happens about 45% of the time. Measured skill per target
is in `models/metrics.json`; retrain with `scripts/train_model.py`.

---

# Troubleshooting

**`pytest` fails instead of skipping on a fresh clone.** You are on an old commit; pull.
Missing data should always skip with the download command in the reason.

**Every web screen shows a load error.** You did not run `split_forecast.py`, so
`forecast/area/` is empty. See step 3.

**`imdlib` writes somewhere unexpected.** It writes `data/rain/<year>.grd`, lowercase, not
`data/imd/<year>.GRD`. Our scripts already account for this; custom scripts often do not.

**Rainfall sums look enormous.** IMD flags sea and no-data cells as **−999**. Mask with
`rain.where(rain >= 0)` — never `rain.where(rain < 1000)`, which keeps the flag and lets it
accumulate silently into every rolling sum. This one is pinned by a test.

**MJO columns are empty for recent seasons.** BoM moved the RMM feed. The old path still
returns `200 OK` with a well-formed file frozen at 2024-02-24 — silent staleness, no error.
Rerun `download_indices.py`; a test fails if RMM ends before the last training season.

**ERA5 stops with HTTP 429.** Expected. Open-Meteo's archive API caps by the hour and
weights each call by locations × time range. Use `./scripts/run_era5_until_done.sh`, which
restarts after each cap and skips what is already cached.

**Port 5173 already in use.** `lsof -ti:5173 | xargs kill`.

**Tests pass locally but the web build is stale.** Browsers cache the bundle hard. Add a
cache-busting query or hard-reload before concluding anything about the CSS.

---

# Layout

```
scripts/     one job each, all resumable, all runnable standalone
src/varshadrishti/
  data/      rainfall loaders — IMD, ERA5, CHIRPS behind one interface
  features/  labels.py (onset/false-onset/dry-spell) · build.py · indices.py
  geo/       boundary dissolve + cell→area weight matrices
  rules/     the CRIDA advisory engine — regex-parsed YAML, never eval
  model/     P5, not written yet
rules/       default.yaml + districts/*.yaml — district plans override by rule id
schema/      the frozen data contract (JSON Schema 2020-12)
web/         React + Vite PWA
services/    telegram + whatsapp + sms senders, shared advisory_text.py
tests/       one file per phase, P0 → P4
```

## Conventions

- **Short comments, one line**, placed at the point of confusion — not docstring essays.
- **Test after each phase**, on a branch named `phase/pN-<slug>`.
- **Nothing bulk gets committed.** Single `.gitignore` at the root; no per-directory ones.
- The data contract in `schema/` is frozen. It has caught four real bugs before they
  shipped; if your change fights it, the change is usually wrong.
