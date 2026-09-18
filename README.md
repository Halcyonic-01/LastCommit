# VarshaDrishti

Hyperlocal monsoon **onset, false-onset and dry-spell** probability system at block and
panchayat scale. Karnataka pilot, national architecture.

SIH 2026 · PS 26086 · Ministry of Earth Sciences (MoES) / NCMRWF

> A farmer sows on a false onset just before a long pause and loses the crop to moisture
> stress. That case is our first-class output — we predict the *gap behind the rain*, not
> just the rain.

## What it does

ECMWF EC46 (51 members, 46 days) + a LightGBM model trained on 34 seasons of IMD rainfall
and ENSO/IOD/MJO indices → blended by lead time, isotonically calibrated → probabilities of
onset, false onset, dry spell and heavy rain at 1–4 weeks → ICAR-CRIDA-cited crop advisories
→ delivered in Kannada by voice, WhatsApp and Telegram.

Scored with **Brier Skill Score against climatology**, never bare accuracy.

Runs on GitHub Actions and static JSON. **₹0/month.**

## Setup

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env    # fill in keys
```

## Get the data (~860 MB, ~23 min)

```bash
.venv/bin/python scripts/download_imd.py       # 34 years IMD 0.25deg rainfall
.venv/bin/python scripts/download_indices.py   # ONI, Nino3.4, DMI, RMM MJO
.venv/bin/python scripts/download_crida.py     # 7 district contingency plans
.venv/bin/python scripts/download_chirps.py    # CHIRPS 0.05deg Karnataka, 2015-2025
```

`download_chirps.py` pulls the **panchayat-scale** layer: 0.05° (~5.5 km) vs IMD's 0.25°
(~27.5 km) — 12,880 Karnataka cells instead of ~300. It subsets the CHC server lazily over
HTTP range requests, so a season costs 2.7 MB and ~45 s rather than a 1 GB yearly global file.

`scripts/download_era5_insurance.py` is the ERA5-Land fallback if IMD Pune is down.

## Test

```bash
.venv/bin/python -m pytest -q
```

## Plan

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — priority-ordered P0→P11, worked
strictly top-down.
