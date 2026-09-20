"""Freeze the tables the XGBoost backend needs at inference, so CI does not need the archive.

Same reasoning as export_inference_tables.py: the nightly Action has the repo, not the
825 MB IMD archive or the raw index files. Two outputs:

  clim_train_only.parquet   per (cell_id, sday) climatology from 1991-2015 only, which is
                            what the boosters were fitted on - NOT the full-period means
                            that features.parquet ships.
  extended_daily.parquet    the 45 date-indexed circulation/MJO predictors.

Rerun whenever data/raw/indices_w4 or rmm_mjo.txt is refreshed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti.features import extended as EX  # noqa: E402

PROC = ROOT / "data" / "processed"


def main() -> None:
    clim = (EX._rain_climatology(EX.TRAIN_YEARS)
              .merge(EX._onset_climatology(EX.TRAIN_YEARS), on="cell_id", how="left"))
    clim.to_parquet(EX.CLIM_TRAIN_PATH, index=False)
    print(f"{EX.CLIM_TRAIN_PATH.relative_to(ROOT)}: {len(clim):,} rows x {clim.shape[1]} cols")

    ext = EX.build_extended_frame()
    ext.to_parquet(EX.EXTENDED_DAILY_PATH)
    print(f"{EX.EXTENDED_DAILY_PATH.relative_to(ROOT)}: {len(ext):,} rows x {ext.shape[1]} cols "
          f"({ext.index.min().date()} -> {ext.index.max().date()})")


if __name__ == "__main__":
    main()
