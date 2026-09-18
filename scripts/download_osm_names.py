"""Fetch Kannada place names (name:kn) for Karnataka districts and taluks from OSM.

KGIS ships English names only, and mechanical transliteration mangles them
(Mysuru -> the wrong glyphs). OSM carries human-entered name:kn tags.
Hoblis are not mapped at this level, so they fall back to English.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "osm"
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]
UA = {"User-Agent": "VarshaDrishti/0.1 (SIH 2026 PS 26086; research)"}

QUERY = (
    '[out:json][timeout:90];'
    'area["ISO3166-2"="IN-KA"][admin_level=4]->.ka;'
    '(relation(area.ka)["boundary"="administrative"]'
    '["admin_level"~"^(5|6|7)$"]["name:kn"];);'
    "out tags center;"
)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "karnataka_names_kn.json"

    if dest.exists() and dest.stat().st_size > 10_000:
        log(f"{dest.name} already on disk, skipping")
        return 0

    data = None
    qs = urllib.parse.urlencode({"data": QUERY})
    for attempt, api in enumerate([m for m in MIRRORS for _ in (0, 1)], 1):
        try:
            req = urllib.request.Request(f"{api}?{qs}", headers=UA)
            data = json.loads(urllib.request.urlopen(req, timeout=180).read())
            break
        except Exception as exc:  # noqa: BLE001 — public Overpass 504s often
            log(f"  attempt {attempt} ({api.split('/')[2]}) failed: {exc}")
            time.sleep(5 * attempt)
    if data is None:
        log("all Overpass mirrors failed — rerun later; Kannada names are non-blocking")
        return 1

    names = {}
    for e in data.get("elements", []):
        t = e.get("tags", {})
        en, kn = t.get("name"), t.get("name:kn")
        if not (en and kn):
            continue
        names[en] = {"kn": kn, "admin_level": t.get("admin_level")}

    dest.write_text(json.dumps(names, ensure_ascii=False, indent=1), encoding="utf-8")
    levels = {}
    for v in names.values():
        levels[v["admin_level"]] = levels.get(v["admin_level"], 0) + 1
    log(f"{len(names)} Kannada names -> {dest.name} | by admin_level: {levels}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
