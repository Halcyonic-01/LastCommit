"""Download ENSO, IOD and MJO climate indices."""

import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "indices"

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
        try:
            req = urllib.request.Request(url, headers=UA)
            body = urllib.request.urlopen(req, timeout=60).read()
            (OUT / name).write_bytes(body)
            lines = body.count(b"\n")
            log(f"{name:14s} {len(body) / 1024:7.1f} KB  {lines:6d} lines")
        except Exception as exc:  # noqa: BLE001
            log(f"{name:14s} FAILED: {exc}")
            failed.append(name)

    log(f"DONE | failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
