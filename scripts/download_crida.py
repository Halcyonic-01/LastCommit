"""P0: Download ICAR-CRIDA district agriculture contingency plans.

These PDFs are the agronomic ground truth for the advisory rules engine (P8).
Every advisory VarshaDrishti emits cites a table from one of these documents -
that is what keeps an LLM out of the decision path.

Each plan contains, per district:
  - early-season drought (delayed onset) by delay period: 2 / 4 / 6 weeks
  - normal onset followed by a 15-20 day dry spell after sowing
  - mid-season drought at vegetative and flowering stage
  - unusual rains and waterlogging
each row naming the farming situation, the normal crop, the change, and the
agronomic measures.

Pilot: 5 Karnataka districts + Bengaluru Rural, plus Yavatmal (Vidarbha) to
prove the rule format generalises beyond the pilot state.
"""

import html
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "crida"
INDEX = "https://www.icar-crida.res.in/Crop_Contingency_Plan.html"
BASE = "https://www.icar-crida.res.in/"

# substring -> output filename (matched case-insensitively against the href)
WANTED = {
    "tumkur": "KA_Tumakuru.pdf",
    "chitradurga": "KA_Chitradurga.pdf",
    "chickballapur": "KA_Chikkaballapur.pdf",
    "davanagere": "KA_Davanagere.pdf",
    "kolar": "KA_Kolar.pdf",
    "bengaluru_rural": "KA_BengaluruRural.pdf",
    "akola/yavatmal": "MH_Yavatmal_Vidarbha.pdf",
}

UA = {"User-Agent": "VarshaDrishti/0.1 (SIH 2026 PS 26086; research)"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(INDEX, headers=UA)
    page = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
    hrefs = [html.unescape(h) for h in re.findall(r'href="([^"]+\.pdf)"', page, re.I)]
    log(f"index lists {len(hrefs)} PDFs")

    failed = []
    for needle, fname in WANTED.items():
        match = next((h for h in hrefs if needle.lower() in h.lower()), None)
        if not match:
            log(f"{fname:28s} NOT FOUND in index (needle={needle!r})")
            failed.append(fname)
            continue

        dest = OUT / fname
        if dest.exists() and dest.stat().st_size > 10_000:
            log(f"{fname:28s} already on disk, skipping")
            continue

        url = urllib.parse.urljoin(BASE, urllib.parse.quote(match, safe="/:%"))
        try:
            r = urllib.request.Request(url, headers=UA)
            body = urllib.request.urlopen(r, timeout=120).read()
            if not body.startswith(b"%PDF"):
                raise ValueError(f"not a PDF (starts {body[:8]!r})")
            dest.write_bytes(body)
            log(f"{fname:28s} {len(body) / 1024:7.0f} KB")
        except Exception as exc:  # noqa: BLE001
            log(f"{fname:28s} FAILED: {exc}")
            failed.append(fname)
        time.sleep(1)

    total = sum(f.stat().st_size for f in OUT.glob("*.pdf")) / 1e6
    log(f"DONE | {len(list(OUT.glob('*.pdf')))} PDFs, {total:.1f} MB | failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
