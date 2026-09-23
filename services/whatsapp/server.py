"""WhatsApp Server Daemon & CLI Runner for VarshaDrishti.

Usage:
  python services/whatsapp/server.py --mode live       # Start live WhatsApp daemon
  python services/whatsapp/server.py --mode alerts     # Evaluate & dispatch proactive alerts
  python services/whatsapp/server.py --mode morning    # Send 6:00 AM morning briefings
  python services/whatsapp/server.py --mode test       # Run self-test using mock backend
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from services.voice.providers import get_voice_provider
from services.whatsapp.mock_backend import MockWhatsAppBackend
from services.whatsapp.service import WhatsAppService
from services.whatsapp.alert_engine import (
    dispatch_proactive_alerts,
    dispatch_morning_briefings,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("whatsapp_server")


def main() -> None:
    parser = argparse.ArgumentParser(description="VarshaDrishti WhatsApp Service Daemon")
    parser.add_argument(
        "--mode",
        choices=["live", "alerts", "morning", "test"],
        default="live",
        help="Execution mode (live daemon, proactive alerts, morning briefings, or mock test)",
    )
    parser.add_argument(
        "--backend",
        choices=["neonize", "mock"],
        default=os.environ.get("WHATSAPP_BACKEND", "neonize"),
        help="WhatsApp communication backend (neonize or mock)",
    )
    parser.add_argument(
        "--session",
        default=os.environ.get("WHATSAPP_SESSION_PATH", "data/whatsapp/session.sqlite3"),
        help="Path to SQLite session database for Neonize",
    )
    parser.add_argument(
        "--pair-phone",
        default=os.environ.get("WHATSAPP_PAIR_PHONE", ""),
        help="Phone number to generate 8-character PairPhone link code",
    )
    args = parser.parse_args()

    voice_provider = get_voice_provider()
    log.info("Voice provider: %s (configured: %s)", voice_provider.name, voice_provider.is_configured())

    if args.backend == "mock" or args.mode == "test":
        backend = MockWhatsAppBackend()
    else:
        try:
            from services.whatsapp.neonize_backend import NeonizeBackend
            backend = NeonizeBackend(
                session_name=args.session,
                pair_phone=args.pair_phone or None,
            )
        except Exception as exc:
            log.warning("Could not initialize NeonizeBackend (%s). Falling back to MockWhatsAppBackend.", exc)
            backend = MockWhatsAppBackend()

    service = WhatsAppService(backend=backend, voice_provider=voice_provider)

    if args.mode == "live":
        if isinstance(backend, MockWhatsAppBackend):
            print("Cannot run live mode with MockWhatsAppBackend. Please configure neonize.")
            sys.exit(1)
        log.info("Starting live Neonize WhatsApp daemon (session: %s)...", args.session)
        backend.run(service)

    elif args.mode == "alerts":
        log.info("Evaluating proactive threshold alerts across all subscribers...")
        dispatched = dispatch_proactive_alerts(backend=backend, voice_provider=voice_provider)
        log.info("Proactive alerts evaluation complete. Dispatched: %d alerts.", len(dispatched))

    elif args.mode == "morning":
        log.info("Dispatching 6:00 AM morning briefings across all subscribers...")
        dispatched = dispatch_morning_briefings(backend=backend, voice_provider=voice_provider)
        log.info("Morning briefings complete. Dispatched: %d briefings.", len(dispatched))

    elif args.mode == "test":
        print("Running WhatsApp service self-check with MockWhatsAppBackend...")
        # 1. Test incoming text with unknown user
        resp1 = service.handle_incoming_text("919999999999", "Will it rain tomorrow?")
        print("1. Unknown user test response:", resp1.intent, "-", resp1.reply_text)
        assert resp1.intent == "missing_location"

        # 2. Register location Bailahongala
        service.update_farmer_location("919999999999", "KGIS-H-010901", lang="kn", name="Test Farmer")
        resp2 = service.handle_incoming_text("919999999999", "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?")
        print("2. Registered user test response:", resp2.intent, "-", resp2.reply_text)
        assert resp2.intent == "rain_tomorrow"

        print("Self-check completed successfully!")


if __name__ == "__main__":
    main()
