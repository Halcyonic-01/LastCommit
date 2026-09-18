#!/usr/bin/env bash
# ERA5 backfill is resumable; restart it if the network drops it.
cd "$(dirname "$0")/.."
for i in $(seq 1 12); do
  .venv/bin/python scripts/download_era5_insurance.py && break
  echo "[wrapper] attempt $i ended early, resuming in 30s"
  sleep 30
done
