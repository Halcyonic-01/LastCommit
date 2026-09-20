"""Score rows with the shipped models. `python scripts/predict.py --help`"""

import argparse
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

from varshadrishti.features import extended as EX  # noqa: E402
from varshadrishti.model import predict_xgb as PX  # noqa: E402

FEATURES = ROOT / "data" / "processed" / "features.parquet"


def main():
    a = argparse.ArgumentParser(description="Probabilities from the trained models.")
    a.add_argument("--features", default=str(FEATURES), help="parquet of feature rows")
    a.add_argument("--date", help="score one date, e.g. 2024-07-15")
    a.add_argument("--area", help="filter to one cell_id")
    a.add_argument("--limit", type=int, default=10)
    a.add_argument("--out", help="write the full result to this parquet instead of printing")
    args = a.parse_args()

    df = pd.read_parquet(args.features)
    if args.date:
        df = df[df["date"] == pd.Timestamp(args.date)]
    if args.area:
        df = df[df["cell_id"] == args.area]
    if df.empty:
        print("no rows matched")
        return 1

    # the boosters need train-only climatology and the extended predictors, not the
    # full-period clim_* that features.parquet ships
    df = EX.attach(df)
    out = pd.concat([df[["date", "cell_id"]].reset_index(drop=True),
                     PX.predict_all(df).reset_index(drop=True)], axis=1)
    if args.out:
        out.to_parquet(args.out, index=False)
        print(f"{len(out):,} rows -> {args.out}")
    else:
        pd.set_option("display.width", 200, "display.max_columns", 30)
        print(out.head(args.limit).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
