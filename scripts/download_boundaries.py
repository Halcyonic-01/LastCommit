"""Download KGIS Karnataka boundary geopackages (district, taluk, hobli)."""

import sys
import time
import urllib.request
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "boundaries"
BASE = "https://github.com/samashti/KGIS/raw/main/data/output"
LAYERS = ["District_Boundaries", "Taluk_Boundaries", "Hobli_Boundaries"]

UA = {"User-Agent": "VarshaDrishti/0.1 (SIH 2026 PS 26086; research)"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failed = []

    for name in LAYERS:
        gpkg = OUT / f"{name}.gpkg"
        if gpkg.exists() and gpkg.stat().st_size > 100_000:
            log(f"{name:22s} already extracted, skipping")
            continue

        zpath = OUT / f"{name}.gpkg.zip"
        try:
            if not (zpath.exists() and zpath.stat().st_size > 100_000):
                t = time.time()
                req = urllib.request.Request(f"{BASE}/{name}.gpkg.zip", headers=UA)
                zpath.write_bytes(urllib.request.urlopen(req, timeout=300).read())
                log(f"{name:22s} {zpath.stat().st_size / 1e6:6.1f} MB in {time.time() - t:.0f}s")

            with zipfile.ZipFile(zpath) as z:
                members = [m for m in z.namelist() if m.endswith(".gpkg")]
                if not members:
                    raise ValueError(f"no .gpkg inside {zpath.name}: {z.namelist()[:5]}")
                with z.open(members[0]) as src:
                    gpkg.write_bytes(src.read())
            log(f"{name:22s} extracted -> {gpkg.stat().st_size / 1e6:.1f} MB")
        except Exception as exc:  # noqa: BLE001
            log(f"{name:22s} FAILED: {exc}")
            failed.append(name)

    log(f"DONE | failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
