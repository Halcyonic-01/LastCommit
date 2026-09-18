"""P0: Download IMD 0.25 deg gridded daily rainfall, 1991-2024.

Downloads year by year so progress is visible and the job is resumable:
a year whose .GRD already exists on disk is skipped. Run under nohup;
it is the longest-latency step of the build.

Source: IMD Pune (imdpune.gov.in) via imdlib.
Grid: 135 lon x 129 lat @ 0.25 deg, 66.5-100.0E / 6.5-38.5N.
Size: ~24 MB/year, ~825 MB total.
"""

import sys
import time
from pathlib import Path

import imdlib as imd

START_YR, END_YR = 1991, 2024
VAR = "rain"
DATA = Path(__file__).resolve().parent.parent / "data"
# imdlib writes to <file_dir>/<var>/<year>.grd
OUT = DATA / VAR


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    years = range(START_YR, END_YR + 1)
    t0 = time.time()
    ok, skipped, failed = 0, 0, []

    for yr in years:
        target = OUT / f"{yr}.grd"
        if target.exists() and target.stat().st_size > 1_000_000:
            log(f"{yr} already on disk ({target.stat().st_size / 1e6:.1f} MB), skipping")
            skipped += 1
            continue

        for attempt in (1, 2, 3):
            try:
                t = time.time()
                imd.get_data(VAR, yr, yr, fn_format="yearwise", file_dir=str(DATA))
                size = target.stat().st_size / 1e6 if target.exists() else 0
                log(f"{yr} done in {time.time() - t:.0f}s ({size:.1f} MB)")
                ok += 1
                break
            except Exception as exc:  # noqa: BLE001 - network flakiness is the norm here
                log(f"{yr} attempt {attempt} failed: {exc}")
                if attempt == 3:
                    failed.append(yr)
                else:
                    time.sleep(5 * attempt)

    mins = (time.time() - t0) / 60
    log(f"FINISHED in {mins:.1f} min | ok={ok} skipped={skipped} failed={failed}")
    total = sum(f.stat().st_size for f in OUT.glob("*.grd")) / 1e6
    log(f"Total on disk: {total:.0f} MB across {len(list(OUT.glob('*.grd')))} files")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
