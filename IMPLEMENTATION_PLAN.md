# VarshaDrishti — Implementation Plan

**SIH 2026 · PS 26086 — Hyperlocal Monsoon Onset & Break Prediction System (Block/Village Scale)**
Ministry of Earth Sciences (MoES) / NCMRWF · Software · Agriculture, FoodTech & Rural Development

> Block- and panchayat-level monsoon onset, **false-onset** and dry-spell probability system for India,
> piloted in Karnataka, turning forecasts into ICAR-CRIDA-cited sowing decisions delivered in regional
> languages by voice and WhatsApp, on a ₹0/month stack.

| | |
|---|---|
| **Started** | Sat 19 Sep 2026, 00:00 IST |
| **Internal deadline** | Mon 21 Sep 2026, 09:00 IST (57 h) |
| **SIH deadline** | 30 Sep 2026 |
| **Team size** | 1 (solo) |

## How to read this plan

Work **strictly top-down**. Nothing here is optional — but the order is the risk management.
Whatever is unreached at Mon 09:00 is unreached at the *bottom* of the list, where it costs
least, instead of leaving a half-built middle that breaks the demo.

Two invariants that make that work:

1. **P1 freezes the data contract before anything consumes it.** The app is built against
   correctly-shaped fake data from hour two, so the model landing late never blocks the UI.
2. **P3 delivers a complete demo by Saturday lunch.** Every hour after that *improves* a demo
   that already exists, instead of gambling that one appears by Monday.

---

## The four PS deliverables (all in scope)

1. Hybrid model pairing global climate indices (ENSO, IOD, MJO) with regional weather data → local rainfall anomalies, onset, active/break durations. → **P4, P5, P6**
2. Colour-coded risk maps at block/panchayat level, probability %, 1–4 weeks ahead. → **P2, P3, P9**
3. Expert system turning probabilities into crop-specific agronomic advisories. → **P8**
4. Mobile-optimised web app + SMS/WhatsApp gateway, regional languages. → **P3, P9**

## The five differentiators

- **False-onset probability as a headline output** — not "onset yes/no"
- **ICAR-CRIDA-grounded advisories** — every advisory carries a table citation, no LLM in the decision path
- **Honest verification** — Brier Skill Score vs climatology, reliability diagram, never bare accuracy
- **Community rain reports** — farmers as ground truth where no gauge exists
- **Zero-server architecture** — GitHub Actions writes static JSON, ₹0/month, scales 300 → 4,700 cells

---

## Tech stack

### Data
| Purpose | Source | Notes |
|---|---|---|
| Truth + climatology | IMD 0.25° gridded daily rainfall 1991–2024 via `imdlib` | 135×129 grid, ~24.3 MB/yr, ~825 MB |
| Truth fallback | Open-Meteo Archive API (ERA5-Land) | Same points, insurance against IMD stalling |
| Live NWP | Open-Meteo **Seasonal** API — ECMWF EC46 | ✅ verified: 46 days, 50 members + control |
| Second NWP | Open-Meteo Ensemble API — GEFS 35-day | Model diversity, if time |
| ENSO | NOAA PSL ONI + Niño 3.4 | Monthly → forward-fill to daily |
| IOD | NOAA PSL DMI (HadISST long) | Monthly → forward-fill |
| MJO | BoM RMM (RMM1, RMM2, phase, amplitude) | Daily since 1974 |
| Boundaries (national) | LGD codes + India Geodata tehsil/village | **Primary keys** — makes a 2nd state a config change |
| Boundaries (Karnataka) | KGIS taluk/hobli/village/GP; `samashti/KGIS` | Simplify via mapshaper to <1 MB |
| Pilot gauges | KSNDMC hobli rainfall (email request, ~10 d) | Phase 2 — request early, never depend on it |
| Agronomy | ICAR-CRIDA district contingency plans | Tumakuru, Chitradurga, Chikkaballapur, Davanagere, Kolar + 1 Vidarbha |

### Compute & model
`python 3.12` · `xarray` · `netCDF4` · `rioxarray` · `geopandas` · `shapely` · `pyproj` · `fiona`
· `pandas` · `numpy` · `lightgbm` · `scikit-learn` (isotonic calibration, Brier, ROC-AUC, LOYO CV)
· `matplotlib` · mapshaper · local M4 (Colab/Kaggle as backup)

### Pipeline & storage
GitHub Actions cron (nightly, free on public repos) · static JSON committed to repo → Vercel CDN
· Supabase (Postgres + PostGIS) for subscribers, rain reports, message + broadcast log

### Frontend
`React 18` + `Vite` + `vite-plugin-pwa` (offline cache, installable) · `MapLibre GL JS` + CARTO/OSM
tiles · `react-i18next` (kn / hi / en / te-or-mr) · Web Speech API (on-device Kannada TTS)
· `Recharts` (reliability diagram, skill-by-lead) · Vercel hosting

### Messaging & voice
Meta WhatsApp Cloud API (test number, 5 verified recipients) · Telegram Bot API (unlimited backup)
· Twilio trial SMS · Sarvam Bulbul pre-rendered Kannada audio (₹100 signup credit)

### Optional
Sarvam-30B / Groq / Gemini free tier for an "ask a question" chat — **never in the decision path**
· FastAPI on Hugging Face Spaces if on-demand inference is needed

---

# Priority-ordered plan

## ▶ P0 — Start every download and every account clock `00:00–01:00`

Everything here is latency-bound: it runs while you sleep, but only if it starts now.

### Automated (scripted)
- [x] Project structure + `python3.12` venv
- [x] `imdlib` installed
- [x] **IMD rainfall 1991–2024 download launched** — `scripts/download_imd.py`, resumable, 3 retries/year
- [x] **EC46 verified** — 46 days, 50 members + control, multi-coordinate batching works, ~4.7 MB/night for 300 cells
- [x] Climate indices downloaded — ONI, Niño 3.4, DMI, RMM (18,168 daily MJO rows)
- [ ] Open-Meteo ERA5 archive insurance pull
- [ ] KGIS Karnataka shapefiles (taluk, hobli, village, GP)
- [ ] ICAR-CRIDA contingency plan PDFs — 5 Karnataka districts + 1 Vidarbha
- [ ] `git init` + first commit

### Manual — cannot be scripted, longest human latency first
- [ ] **Meta developer app + WhatsApp Cloud API test number** (needs a Facebook account; slowest)
- [ ] **KSNDMC daily hobli data request email** (~10-day turnaround — send tonight or it is worthless)
- [ ] Supabase project, **PostGIS enabled**, keys saved to `.env`
- [ ] GitHub repo created, Vercel linked for auto-deploy
- [ ] Telegram bot via `@BotFather`
- [ ] Twilio trial account
- [ ] Sarvam AI signup (₹100 credit)

**Done when:** IMD bytes on disk, indices on disk, EC46 verified, all accounts exist.

## P1 — Freeze the data contract `01:00–02:00` → then sleep

The single most leveraged hour. Everything downstream meets at `latest.json`.

Split static geometry from daily probabilities — the 200 KB/day 2G budget forbids re-shipping polygons:

- `geo/blocks.geojson`, `geo/hoblis.geojson` — static, cached hard, fetched once
- `forecast/latest.json` — keyed by LGD code → `p_onset`, `p_false_onset`, `p_dry7`, `p_dry14`,
  `p_heavy` at `w1..w4`, plus `onset_delay_weeks`, `confidence`, `advisories[]`
- `forecast/YYYY-MM-DD.json` — same shape, dated, feeds replay mode

- [ ] Write `schema/forecast.schema.json` and freeze it
- [ ] Commit hand-faked Tumakuru data in that exact shape
- [ ] **Sleep 02:00–08:00.** Solo, sleep is infrastructure.

## P2 — Boundaries and the aggregation table `Sat 08:00–10:00`

- [ ] KGIS → mapshaper → sub-1 MB GeoJSON, taluk + hobli
- [ ] LGD codes wired as primary keys throughout
- [ ] **Precompute the grid-cell → polygon area-weight matrix once** and commit it — the nightly
      job then does a matrix multiply, not a spatial join (30 s Action instead of 5 min)

## P3 — End-to-end vertical slice `Sat 10:00–14:00` ⭐

Built entirely against the fake JSON. **By Saturday lunch there is a demo.**

- [ ] PWA shell, routes (`/`, `/officer`), service worker
- [ ] 3-tap onboarding: language → location → crop
- [ ] Home card: colour + icon + one Kannada sentence + play button
- [ ] 4-week coloured chip strip
- [ ] MapLibre with taluk/hobli polygons reading `latest.json`
- [ ] One YAML advisory rule end-to-end
- [ ] One Telegram message landing on a real phone

## P4 — Labels and features `Sat 14:00–18:00`

Per cell, per season, from IMD rainfall:

| Label | Definition |
|---|---|
| Local onset | First day after 1 Jun starting a 5-day window with ≥25 mm and ≥3 rainy days (≥2.5 mm), **and** no ≥10-day dry spell in the following 30 days |
| **False onset** | Meets the first condition, fails the 30-day check — *the headline label* |
| Dry spell (break) | ≥7 consecutive days <2.5 mm after onset; also a 14-day version (CRIDA mid-season drought keys on two rainless weeks) |
| Heavy rain | Any day ≥64.5 mm (IMD "heavy" threshold) |

Features (Jun–Sep): day-of-year; cell climatological onset date and rainfall; rain in last
1/3/7/14/30 d; days since last rainy day; onset-happened flag; RMM1, RMM2, amplitude, phase
(one-hot); DMI; ONI. ≈300 cells × 34 seasons × 122 days ≈ **1.2 M rows**.

## P5 — Model, calibration, skill `Sat 18:00–22:00`

- [ ] LightGBM binary classifier per target × horizon (onset within 7/14/21/28 d; dry spell within 7/14 d; heavy rain within 7 d)
- [ ] **Split by year, never randomly** — neighbouring cells in one season are the same weather event; a random split leaks and produces a fake 95%
- [ ] Leave-one-year-out CV → isotonic calibration fitted on held-out predictions
- [ ] Brier, **Brier Skill Score vs per-cell climatology**, ROC-AUC, reliability diagram
- [ ] Save model + `metrics.json`

> Sample-size honesty for the stage: 1.2 M rows but only **34 independent seasons**. Say it before the jury does.

## P6 — Live pipeline and the nightly Action `Sat 22:00–01:00`

EC46 fetch → per-cell per-rule member fraction = `P_nwp` · model on today's features = `P_stat`
· blend `w = 0.8 / 0.6 / 0.4 / 0.25` for weeks 1–4 · isotonic calibration curve
· area-weighted aggregation to taluk + hobli · rules engine per hobli × crop
· write `latest.json` + dated file · Supabase upsert · commit → Vercel redeploys.

- [ ] Cache every API response in the repo (one fetch per day, survives outages)
- [ ] **Checkpoint: the real JSON replaces the fake one and the frontend needs _zero_ changes.**
      That is the test that P1 worked.
- [ ] Sleep.

## P7 — Replay mode and skill page `Sun 07:00–11:00` ⭐

Your headroom over IMD's operational block forecast. Protect this block.

- [ ] Hindcast Jun–Aug 2025 → dated forecast files
- [ ] Replay scrubber: forecast map beside what actually happened
- [ ] **Find and bookmark a hobli where the app said "wait" before a false onset** — this single frame is the demo
- [ ] Skill page: BSS by lead time, reliability diagram, ROC-AUC, per-taluk verification

## P8 — Full rules engine, Kannada, voice `Sun 11:00–15:00`

- [ ] Encode CRIDA tables for all 5 Karnataka districts + 1 Vidarbha district:
      early-season drought by delay (2/4/6 weeks); normal onset then a 15–20 day dry spell after
      sowing; mid-season drought at vegetative and flowering; unusual rains and waterlogging
- [ ] Max 3 actions per hobli × crop, each with `action_kn` / `action_en`, a confidence word, and a table citation
- [ ] Hand-translate every Kannada template (finite rule set — no translation API, no hallucinated advisory)
- [ ] Unit-test rules against 5 hand-made forecast scenarios
- [ ] Web Speech API audio; Sarvam Bulbul pre-render for WhatsApp

## P9 — Every surface and channel `Sun 15:00–20:00`

- [ ] Officer dashboard `/officer`: map with layer toggle + week 1–4 slider, risk table sorted by probability with subscriber counts, broadcast composer logging to Supabase, skill page
- [ ] Community rain reports → Supabase → dots on the map
- [ ] "Why?" expander — probabilities in words, confidence gauge, never hidden
- [ ] WhatsApp Cloud API: Wednesday weekly card + threshold alerts
- [ ] Twilio SMS in Kannada; Telegram bot
- [ ] Language switcher wired for all four languages

## P10 — National layer and scale proof `Sun 20:00–22:00`

- [ ] Re-run training on the all-India grid (**the IMD files are already national** — a bigger clip, not a new download)
- [ ] National statistical layer on the map, Karnataka lit in full detail
- [ ] `--state` run live from the terminal for a second state

## P11 — Demo assets `Sun 22:00–00:00` · Rehearse `Mon 07:00–09:00`

Six-minute script, in order:

1. WhatsApp advisory lands on a jury phone, with audio — before anyone opens a laptop
2. PWA as a Tumakuru ragi farmer: 3-tap onboarding, home card, play the audio
3. Officer dashboard replay: scrub Jun 2025, show the app saying "wait" before a false onset, then the July dry-spell advisory
4. Skill page: BSS by lead time, reliability diagram — **say where the model is weak**
5. Run the pipeline for a second state from the terminal — it is a config change
6. ₹0/month cost slide, national scale-up via LGD codes and Agri Stack

- [ ] Slides · demo script · **backup video recorded while everything works**
- [ ] Rehearse twice, freeze the code

---

## Risk register

| Risk | Fallback | Status |
|---|---|---|
| IMD download stalls | Open-Meteo Archive (ERA5-Land), same code path | Retries working; 1992 needed 2 attempts |
| Open-Meteo rate limit / outage | Cache each day's response in the repo | Batching verified — few calls, ~4.7 MB/night |
| Meta test number setup fails | Telegram bot (free, unlimited) + Twilio trial SMS | Not started |
| Model skill ≈ 0 at weeks 3–4 | Show it honestly; advisories limited to weeks 1–2, weeks 3–4 labelled "outlook" | — |
| Live demo network fails | Recorded backup video | — |
| Solo capacity | Strict top-down priority order; P3 guarantees a demo exists by Sat lunch | — |

## What the jury will probe

- **Why Karnataka?** Only state with hobli-level telemetric rain gauges (KSNDMC), so the one place a panchayat-scale forecast can be *verified*. South-interior ragi/groundnut belt is exactly where false onsets cause the losses the PS describes.
- **Why not just IMD's block model?** IMD launched AI block-level onset forecasts (May 2026, 3,196 blocks, 15 states, ~4-day error). Onset is partly solved operationally. Our headroom is **break and false-onset prediction, panchayat-scale downscaling, and the advisory layer**.
- **How were blend weights chosen?** Lead-time skill decay; upgrade path is a logistic stacker on Open-Meteo's archived forecast runs (available from 2024).
- **How does a panchayat value differ from a block value?** Area-weighted grid cells now; KSNDMC hobli gauges for calibration next.
- **Is an LLM writing the advisories?** No. Finite YAML rules with ICAR-CRIDA citations.

## Definition of done (MVP)

One state · both forecast heads (onset/false-onset **and** dry spell) · honest verification numbers
· one advisory rule set · a WhatsApp message that lands on a jury phone. Everything beyond is bonus.
