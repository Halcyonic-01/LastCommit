"""In-memory mock backend for WhatsApp testing and headless CI."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SentTextMessage:
    destination: str
    text: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class SentVoiceMessage:
    destination: str
    audio_bytes: bytes
    caption: str | None = None
    is_ptt: bool = True
    timestamp: float = field(default_factory=time.time)


class MockWhatsAppBackend:
    """Mock backend implementing WhatsApp delivery in-memory."""

    def __init__(self) -> None:
        self.sent_texts: list[SentTextMessage] = []
        self.sent_voices: list[SentVoiceMessage] = []
        self.is_connected: bool = True

    def send_text(self, destination: str, text: str) -> bool:
        """Record a sent text message."""
        self.sent_texts.append(SentTextMessage(destination=destination, text=text))
        return True

    def send_voice(
        self,
        destination: str,
        audio_bytes: bytes,
        caption: str | None = None,
        is_ptt: bool = True,
    ) -> bool:
        """Record a sent voice note."""
        self.sent_voices.append(
            SentVoiceMessage(
                destination=destination,
                audio_bytes=audio_bytes,
                caption=caption,
                is_ptt=is_ptt,
            )
        )
        return True

    def clear(self) -> None:
        """Clear recorded messages."""
        self.sent_texts.clear()
        self.sent_voices.clear()

    def get_last_text(self, destination: str | None = None) -> SentTextMessage | None:
        """Get most recent text message, optionally filtered by recipient."""
        filtered = [
            m for m in self.sent_texts
            if destination is None or m.destination == destination
        ]
        return filtered[-1] if filtered else None

    def get_last_voice(self, destination: str | None = None) -> SentVoiceMessage | None:
        """Get most recent voice message, optionally filtered by recipient."""
        filtered = [
            v for v in self.sent_voices
            if destination is None or v.destination == destination
        ]
        return filtered[-1] if filtered else None
