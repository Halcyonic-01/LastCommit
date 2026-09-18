#!/usr/bin/env bash
# CHIRPS backfill is resumable; the CHC server drops large reads, so retry the whole pass.
cd "$(dirname "$0")/.."
for i in $(seq 1 8); do
  .venv/bin/python scripts/download_chirps.py --start 1991 --end 2025 && break
  echo "[wrapper] pass $i ended with failures, resuming in 20s"
  sleep 20
done
