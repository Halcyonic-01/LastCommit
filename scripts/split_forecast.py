"""Split latest.json into per-area farmer files. Run at deploy time, not committed.

Keeps 1,097 generated files out of git so a nightly commit touches latest.json + index.json
rather than the whole tree. Vercel runs this as its build step.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from varshadrishti import contract as c  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--forecast-dir", default=str(c.FORECAST_DIR))
    args = ap.parse_args()

    d = Path(args.forecast_dir)
    latest = c.load_and_validate(d / "latest.json", "forecast.schema.json")
    meta, skill = latest["meta"], latest["skill"]

    summary = c.provenance_summary(latest)

    worst = 0
    for aid, body in latest["areas"].items():
        payload = {"meta": meta, "forecast": body, "skill": skill, "provenance_summary": summary}
        c.validate(payload, "area.schema.json")
        worst = max(worst, c.write_json(payload, d / "area" / f"{aid}.json", c.AREA_FILE_MAX_BYTES))

    print(f"{len(latest['areas']):,} area files | largest {worst:,} B "
          f"(budget {c.AREA_FILE_MAX_BYTES:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
