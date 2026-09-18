"""Download IMD 0.25deg gridded daily rainfall, 1991-2024."""

import sys
import time
from pathlib import Path

import imdlib as imd

START_YR, END_YR = 1991, 2024
VAR = "rain"
DATA = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT = DATA / VAR  # imdlib writes to <file_dir>/<var>/<year>.grd


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ok, skipped, failed = 0, 0, []

    for yr in range(START_YR, END_YR + 1):
        target = OUT / f"{yr}.grd"
        if target.exists() and target.stat().st_size > 1_000_000:
            skipped += 1
            continue

        for attempt in (1, 2, 3):  # IMD Pune resets connections often
            try:
                t = time.time()
                imd.get_data(VAR, yr, yr, fn_format="yearwise", file_dir=str(DATA))
                size = target.stat().st_size / 1e6 if target.exists() else 0
                log(f"{yr} done in {time.time() - t:.0f}s ({size:.1f} MB)")
                ok += 1
                break
            except Exception as exc:  # noqa: BLE001
                log(f"{yr} attempt {attempt} failed: {exc}")
                if attempt == 3:
                    failed.append(yr)
                else:
                    time.sleep(5 * attempt)

    files = list(OUT.glob("*.grd"))
    total = sum(f.stat().st_size for f in files) / 1e6
    log(f"FINISHED in {(time.time() - t0) / 60:.1f} min | ok={ok} skipped={skipped} failed={failed}")
    log(f"{total:.0f} MB across {len(files)} files")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
