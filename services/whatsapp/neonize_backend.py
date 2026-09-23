"""Neonize Live WhatsApp Backend for VarshaDrishti.

Integrates whatsmeow Go engine via neonize Python bindings.
Handles QR pairing, 8-character phone pairing code, message events,
and audio PTT downloads/uploads.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from neonize.client import NewClient
from neonize.events import ConnectedEv, MessageEv
from neonize.utils import build_jid

if TYPE_CHECKING:
    from services.whatsapp.service import WhatsAppService

log = logging.getLogger(__name__)


class NeonizeBackend:
    """Production WhatsApp client driver backed by Neonize."""

    def __init__(
        self,
        session_name: str = "data/whatsapp/session.sqlite3",
        pair_phone: str | None = None,
    ) -> None:
        self.session_name = session_name
        self.pair_phone = pair_phone or os.environ.get("WHATSAPP_PAIR_PHONE", "").strip()
        # Ensure session directory exists
        Path(self.session_name).parent.mkdir(parents=True, exist_ok=True)
        self.client = NewClient(self.session_name)
        self.is_connected = False

    def send_text(self, destination: str, text: str) -> bool:
        """Send a plain text WhatsApp message."""
        clean_phone = destination.split("@")[0].strip()
        jid = build_jid(clean_phone)
        try:
            self.client.send_message(jid, text)
            log.info("[NEONIZE] Text message delivered to %s", clean_phone)
            return True
        except Exception as exc:
            log.exception("[NEONIZE] Failed to send text to %s: %s", clean_phone, exc)
            return False

    def send_voice(
        self,
        destination: str,
        audio_bytes: bytes,
        caption: str | None = None,
        is_ptt: bool = True,
    ) -> bool:
        """Send a voice note (push-to-talk) message."""
        clean_phone = destination.split("@")[0].strip()
        jid = build_jid(clean_phone)
        try:
            self.client.send_audio(jid, audio_bytes, ptt=is_ptt)
            log.info("[NEONIZE] Voice note delivered to %s (size: %d bytes)", clean_phone, len(audio_bytes))
            return True
        except Exception as exc:
            log.exception("[NEONIZE] Failed to send voice note to %s: %s", clean_phone, exc)
            return False

    def run(self, service: WhatsAppService) -> None:
        """Register event handlers and start the live Neonize client loop."""

        @self.client.event(ConnectedEv)
        def on_connected(client: NewClient, event: ConnectedEv) -> None:
            self.is_connected = True
            log.info("[NEONIZE] Successfully connected to WhatsApp network!")
            if self.pair_phone and not client.is_logged_in:
                try:
                    code = client.PairPhone(self.pair_phone, show_push_notification=True)
                    print("\n" + "=" * 50)
                    print(f"WHATSAPP PAIRING CODE FOR {self.pair_phone}: {code}")
                    print("Enter this code in WhatsApp -> Linked Devices -> Link with phone number")
                    print("=" * 50 + "\n")
                except Exception as exc:
                    log.warning("[NEONIZE] PairPhone error: %s", exc)

        @self.client.event(MessageEv)
        def on_message(client: NewClient, event: MessageEv) -> None:
            # Ignore self-sent messages
            if event.Info.MessageSource.IsFromMe:
                return

            sender_jid = event.Info.MessageSource.Sender
            sender_phone = sender_jid.User
            if not sender_phone:
                return

            log.info("[NEONIZE] Incoming message from %s", sender_phone)

            # 1. Check for incoming audio / voice note
            if event.Message.HasField("audioMessage"):
                try:
                    audio_bytes = client.download_any(event.Message)
                    if audio_bytes:
                        mime = event.Message.audioMessage.mimetype or "audio/ogg"
                        resp = service.handle_incoming_audio(sender_phone, audio_bytes, mime_type=mime)
                        service.dispatch_reply(sender_phone, resp)
                        return
                except Exception as exc:
                    log.exception("[NEONIZE] Error handling incoming audio from %s: %s", sender_phone, exc)

            # 2. Check for incoming text
            text_body = ""
            if event.Message.conversation:
                text_body = event.Message.conversation
            elif event.Message.extendedTextMessage and event.Message.extendedTextMessage.text:
                text_body = event.Message.extendedTextMessage.text

            if text_body:
                try:
                    resp = service.handle_incoming_text(sender_phone, text_body)
                    service.dispatch_reply(sender_phone, resp)
                except Exception as exc:
                    log.exception("[NEONIZE] Error handling incoming text from %s: %s", sender_phone, exc)

        print("[NEONIZE] Connecting to WhatsApp... Scan QR code or wait for phone pairing code.")
        self.client.connect()
