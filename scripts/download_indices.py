"""P0: Download the three climate indices the PS names (ENSO, IOD, MJO).

All three are small text files. They are the "global planetary boundary
conditions" half of the hybrid; the IMD grid is the regional half.

  ONI  (ENSO) - NOAA CPC, monthly, 1950-present
  DMI  (IOD)  - NOAA PSL, monthly, 1870-present
  RMM  (MJO)  - BoM, DAILY since 1974: RMM1, RMM2, phase, amplitude

Monthly series get forward-filled to daily at feature-build time (P4).
"""

import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "indices"

SOURCES = {
    "oni.txt": "https://psl.noaa.gov/data/correlation/oni.data",
    "nino34.txt": "https://psl.noaa.gov/data/correlation/nina34.data",
    "dmi.txt": "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data",
    "rmm_mjo.txt": "http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt",
}

UA = {"User-Agent": "VarshaDrishti/0.1 (SIH 2026 PS 26086; research)"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failed = []
    for name, url in SOURCES.items():
        dest = OUT / name
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            dest.write_bytes(body)
            lines = body.count(b"\n")
            log(f"{name:14s} {len(body) / 1024:7.1f} KB  {lines:6d} lines  <- {url}")
        except Exception as exc:  # noqa: BLE001
            log(f"{name:14s} FAILED: {exc}")
            failed.append(name)

    if failed:
        log(f"FAILED: {failed}")
    else:
        log("All indices downloaded.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
