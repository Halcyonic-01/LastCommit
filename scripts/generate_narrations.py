"""Pre-generate narration audio for key hoblis across languages.

Uses Sarvam Bulbul v3 TTS and stores audio in:
  - web/public/audio/narration/{area_id}_{screen}_{lang}.wav
  - data/cache/audio/ (server-side disk cache)

Usage:
  .venv/bin/python scripts/generate_narrations.py
  .venv/bin/python scripts/generate_narrations.py --area KGIS-H-180901 --lang kn
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services"))

from services.voice.assistant import load_forecast_for_area
from services.voice.narration import build_today_narration, build_why_narration
from services.voice.providers import get_voice_provider
from services.voice.server import _audio_cache_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("generate_narrations")

DEFAULT_AREAS = [
    "KGIS-H-180901",  # Tumakuru - Kasaba (primary demo)
    "KGIS-H-180801",  # Belagavi - Bailahongala
]
DEFAULT_LANGS = ["kn", "hi", "te", "en"]


def main():
    parser = argparse.ArgumentParser(description="Generate narration audio clips")
    parser.add_argument("--area", action="append", help="Area ID to process (default: demo areas)")
    parser.add_argument("--lang", action="append", help="Language code (kn, hi, te, en)")
    parser.add_argument("--dry-run", action="store_true", help="Print narration texts without synthesizing")
    args = parser.parse_args()

    areas = args.area or DEFAULT_AREAS
    langs = args.lang or ["kn"]

    provider = get_voice_provider("sarvam")
    if not args.dry_run and not provider.is_configured():
        log.error("SARVAM_API_KEY is not configured. Run with --dry-run or set key in .env.")
        sys.exit(1)

    out_dir = ROOT / "web" / "public" / "audio" / "narration"
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("Generating narrations for %d area(s) and %d language(s)", len(areas), len(langs))

    for area_id in areas:
        forecast_data = load_forecast_for_area(area_id)
        if not forecast_data:
            log.warning("Could not load forecast for area %s; skipping", area_id)
            continue

        for lang in langs:
            today_text = build_today_narration(forecast_data, lang=lang)
            why_text = build_why_narration(forecast_data, lang=lang)

            log.info("Area: %s | Lang: %s", area_id, lang)
            log.info("  Today: %s", today_text)
            log.info("  Why:   %s", why_text)

            if args.dry_run:
                continue

            # 1. Today narration
            today_file = out_dir / f"{area_id}_today_{lang}.wav"
            try:
                res = provider.synthesize(today_text, lang=lang)
                today_file.write_bytes(res.audio_bytes)
                log.info("  Saved today audio -> %s (%d bytes)", today_file.relative_to(ROOT), len(res.audio_bytes))

                # Prime server disk cache
                cache_file = _audio_cache_path(provider.name, lang, today_text)
                cache_file.write_bytes(res.audio_bytes)

                # For primary demo hobli and Kannada, also update legacy web/public/narration_today_kn.wav
                if area_id == "KGIS-H-180901" and lang == "kn":
                    legacy_file = ROOT / "web" / "public" / "narration_today_kn.wav"
                    legacy_file.write_bytes(res.audio_bytes)
            except Exception as exc:
                log.error("  Failed synthesizing today narration: %s", exc)

            # 2. Why narration
            why_file = out_dir / f"{area_id}_why_{lang}.wav"
            try:
                res = provider.synthesize(why_text, lang=lang)
                why_file.write_bytes(res.audio_bytes)
                log.info("  Saved why audio -> %s (%d bytes)", why_file.relative_to(ROOT), len(res.audio_bytes))

                # Prime server disk cache
                cache_file = _audio_cache_path(provider.name, lang, why_text)
                cache_file.write_bytes(res.audio_bytes)

                # For primary demo hobli and Kannada, also update legacy web/public/narration_why_kn.wav
                if area_id == "KGIS-H-180901" and lang == "kn":
                    legacy_file = ROOT / "web" / "public" / "narration_why_kn.wav"
                    legacy_file.write_bytes(res.audio_bytes)
            except Exception as exc:
                log.error("  Failed synthesizing why narration: %s", exc)

    log.info("Narration generation complete.")


if __name__ == "__main__":
    main()
