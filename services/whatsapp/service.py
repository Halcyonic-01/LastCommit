"""Core WhatsApp Service Layer for VarshaDrishti.

Provides phone resolution, subscriber location management, message dispatching,
and decoupled audio/text processing for farmer communication.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[2]
LOCAL_SUBSCRIBERS = ROOT / "data" / "interim" / "subscribers.jsonl"

sys.path.insert(0, str(ROOT / "src"))
from varshadrishti.data import supabase_client as SB  # noqa: E402
from services.voice.assistant import (
    generate_grounded_answer,
    load_forecast_for_area,
    resolve_area_id_from_text,
)
from services.voice.providers import (
    VoiceProvider,
    get_voice_provider,
    convert_wav_to_opus_ogg,
    STTError,
    TTSError,
)

log = logging.getLogger(__name__)


def normalize_phone(raw: str | None) -> str:
    """Normalize phone number to international format digits (e.g. 919876543210)."""
    if not raw:
        return ""
    # Strip WhatsApp JID suffix if present
    cleaned = raw.split("@")[0].strip()
    # Retain only digits
    digits = re.sub(r"\D", "", cleaned)
    # If 10 digits (standard Indian mobile number), prefix with India country code 91
    if len(digits) == 10:
        return f"91{digits}"
    # If 11 digits starting with 0, replace leading 0 with 91
    if len(digits) == 11 and digits.startswith("0"):
        return f"91{digits[1:]}"
    return digits


@dataclass
class WhatsAppMessage:
    sender: str
    text: str | None = None
    audio_bytes: bytes | None = None
    mime_type: str = "audio/ogg"
    is_ptt: bool = True
    message_id: str = ""
    timestamp: float = 0.0


@dataclass
class WhatsAppResponse:
    reply_text: str
    reply_audio: bytes | None = None
    audio_mime_type: str = "audio/ogg"
    intent: str = "unknown"
    grounding_data: dict[str, Any] = field(default_factory=dict)
    subscriber: dict[str, Any] | None = None


class WhatsAppBackend(Protocol):
    """Protocol defining the interface for WhatsApp delivery backends."""

    def send_text(self, destination: str, text: str) -> bool:
        ...

    def send_voice(
        self,
        destination: str,
        audio_bytes: bytes,
        caption: str | None = None,
        is_ptt: bool = True,
    ) -> bool:
        ...


class WhatsAppService:
    """High-level service coordinating WhatsApp conversations and alerts."""

    def __init__(
        self,
        backend: WhatsAppBackend,
        voice_provider: VoiceProvider | None = None,
    ) -> None:
        self.backend = backend
        self.voice_provider = voice_provider or get_voice_provider()

    # --- Farmer & Subscriber Management ---------------------------------------

    @staticmethod
    def _read_local_subscribers() -> list[dict[str, Any]]:
        if not LOCAL_SUBSCRIBERS.exists():
            return []
        rows = []
        for line in LOCAL_SUBSCRIBERS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    @staticmethod
    def _write_local_subscribers(rows: list[dict[str, Any]]) -> None:
        LOCAL_SUBSCRIBERS.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        LOCAL_SUBSCRIBERS.write_text(content, encoding="utf-8")

    def resolve_farmer(self, phone: str) -> dict[str, Any] | None:
        """Look up a farmer by phone number across Supabase and local storage."""
        norm = normalize_phone(phone)
        if not norm:
            return None

        # Check Supabase first
        sb_subs = SB.fetch_subscribers(channel="whatsapp")
        for sub in sb_subs:
            if normalize_phone(sub.get("destination")) == norm:
                return sub

        # Fallback to local storage
        for sub in self._read_local_subscribers():
            if sub.get("active", True) and normalize_phone(sub.get("destination")) == norm:
                return sub

        return None

    def update_farmer_location(
        self,
        phone: str,
        area_id: str,
        lang: str = "kn",
        name: str | None = None,
        crop: str | None = None,
    ) -> bool:
        """Register or update farmer's hobli location."""
        norm = normalize_phone(phone)
        if not norm or not area_id:
            return False

        # Update local file store
        rows = self._read_local_subscribers()
        updated = False
        for r in rows:
            if normalize_phone(r.get("destination")) == norm:
                r["area_id"] = area_id
                r["lang"] = lang
                if name:
                    r["name"] = name
                if crop:
                    r["crop"] = crop
                r["active"] = True
                updated = True
                break

        if not updated:
            new_row = {
                "destination": norm,
                "area_id": area_id,
                "channel": "whatsapp",
                "lang": lang,
                "name": name,
                "crop": crop,
                "active": True,
            }
            rows.append(new_row)

        self._write_local_subscribers(rows)

        # Sync to Supabase
        SB.add_subscriber(
            area_id=area_id,
            channel="whatsapp",
            destination=norm,
            lang=lang,
            name=name,
            crop=crop,
        )
        return True

    # --- Incoming Message Handlers --------------------------------------------

    def handle_incoming_text(self, sender_phone: str, text: str) -> WhatsAppResponse:
        """Process incoming text message from a farmer."""
        norm_phone = normalize_phone(sender_phone)
        farmer = self.resolve_farmer(norm_phone)
        clean_text = (text or "").strip()

        # Check if farmer is sending or changing their location/hobli
        matched_area = resolve_area_id_from_text(clean_text)
        is_unknown_farmer = farmer is None or not farmer.get("area_id")
        
        # If farmer is unknown and specified a hobli, or explicitly asked to change/set location
        explicit_location_intent = any(
            w in clean_text.lower()
            for w in ["ಹೋಬಳಿ", "ಗ್ರಾಮ", "ಊರು", "ಸ್ಥಳ", "change to", "location", "hobli", "village", "from"]
        )

        if matched_area and (is_unknown_farmer or explicit_location_intent):
            farmer_lang = farmer.get("lang", "kn") if farmer else "kn"
            self.update_farmer_location(norm_phone, matched_area, lang=farmer_lang)
            farmer = self.resolve_farmer(norm_phone)

            forecast_data = load_forecast_for_area(matched_area)
            if forecast_data and "forecast" in forecast_data:
                fc = forecast_data["forecast"]
                place_kn = fc.get("name_kn") or fc.get("name_en", matched_area)
                place_en = fc.get("name_en", matched_area)
                if farmer_lang == "kn":
                    confirm_text = f"ನಿಮ್ಮ ಸ್ಥಳವನ್ನು {place_kn} ಗೆ ನವೀಕರಿಸಲಾಗಿದೆ. ಈಗ ನೀವು ಹವಾಮಾನ ಮತ್ತು ಕೃಷಿ ಸಲಹೆಗಳನ್ನು ಪಡೆಯಬಹುದು."
                elif farmer_lang == "hi":
                    confirm_text = f"आपका स्थान {place_en} पर सेट कर दिया गया है। अब आप मौसम और कृषि सलाह प्राप्त कर सकते हैं।"
                elif farmer_lang == "te":
                    confirm_text = f"మీ ప్రాంతం {place_en} గా నవీకరించబడింది. ఇప్పుడు మీరు వాతావరణ సమాచారం పొందవచ్చు."
                else:
                    confirm_text = f"Your location has been updated to {place_en}. You can now ask for weather forecasts and agricultural advice."
            else:
                confirm_text = "ನಿಮ್ಮ ಸ್ಥಳವನ್ನು ನವೀಕರಿಸಲಾಗಿದೆ." if farmer_lang == "kn" else "Your location has been updated."

            return WhatsAppResponse(
                reply_text=confirm_text,
                reply_audio=None,
                intent="location_updated",
                grounding_data={"area_id": matched_area},
                subscriber=farmer,
            )

        # Standard agricultural / forecast question
        farmer_area = farmer.get("area_id") if farmer else None
        farmer_lang = farmer.get("lang", "kn") if farmer else "kn"

        res = generate_grounded_answer(clean_text, lang=farmer_lang, area_id=farmer_area)

        return WhatsAppResponse(
            reply_text=res["reply_text"],
            reply_audio=None,
            intent=res["action"],
            grounding_data=res.get("grounding_data", {}),
            subscriber=farmer,
        )

    def handle_incoming_audio(
        self,
        sender_phone: str,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
    ) -> WhatsAppResponse:
        """Process incoming voice message from a farmer."""
        norm_phone = normalize_phone(sender_phone)
        farmer = self.resolve_farmer(norm_phone)
        farmer_lang = farmer.get("lang", "kn") if farmer else "kn"

        # 1. Speech-to-Text via Sarvam
        try:
            stt_res = self.voice_provider.transcribe(
                audio_bytes,
                audio_format=mime_type,
                lang=farmer_lang,
            )
            transcript = stt_res.transcript
        except (STTError, Exception) as exc:
            log.warning("[WHATSAPP] STT transcription failed: %s", exc)
            err_replies = {
                "kn": "ಕ್ಷಮಿಸಿ, ಧ್ವನಿ ಸಂದೇಶವನ್ನು ಪ್ರಕ್ರಿಯೆಗೊಳಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಪಠ್ಯ ಸಂದೇಶ ಕಳುಹಿಸಿ ಅಥವಾ ಸ್ಪಷ್ಟವಾಗಿ ಮತ್ತೆ ಮಾತನಾಡಿ.",
                "hi": "क्षमा करें, ध्वनि संदेश समझ नहीं आया। कृपया टेक्स्ट संदेश भेजें या फिर से बोलें।",
                "te": "క్షమించండి, వాయిస్ సందేశం అర్థం కాలేదు. దయచేసి టెక్స్ట్ సందేశం పంపండి.",
                "en": "Sorry, could not process voice message. Please send a text message or speak clearly.",
            }
            clean_lang = farmer_lang.lower().split("-")[0]
            return WhatsAppResponse(
                reply_text=err_replies.get(clean_lang, err_replies["kn"]),
                reply_audio=None,
                intent="stt_failed",
                grounding_data={"error": str(exc)},
                subscriber=farmer,
            )

        # 2. Get grounded answer for transcribed query
        text_resp = self.handle_incoming_text(norm_phone, transcript)

        # 3. Text-to-Speech via Sarvam
        reply_audio = None
        try:
            tts_res = self.voice_provider.synthesize(text_resp.reply_text, lang=farmer_lang)
            # Convert WAV to WhatsApp PTT compatible OGG/Opus
            ogg_bytes = convert_wav_to_opus_ogg(tts_res.audio_bytes)
            if ogg_bytes:
                reply_audio = ogg_bytes
            else:
                reply_audio = tts_res.audio_bytes
        except (TTSError, Exception) as exc:
            log.warning("[WHATSAPP] TTS synthesis failed: %s (falling back to text-only reply)", exc)
            reply_audio = None

        return WhatsAppResponse(
            reply_text=text_resp.reply_text,
            reply_audio=reply_audio,
            audio_mime_type="audio/ogg" if reply_audio else "",
            intent=text_resp.intent,
            grounding_data={**text_resp.grounding_data, "transcript": transcript},
            subscriber=farmer,
        )

    def dispatch_reply(self, sender_phone: str, response: WhatsAppResponse) -> None:
        """Send response back to farmer via backend."""
        norm_phone = normalize_phone(sender_phone)
        if response.reply_audio:
            self.backend.send_voice(
                norm_phone,
                response.reply_audio,
                caption=response.reply_text,
                is_ptt=True,
            )
        self.backend.send_text(norm_phone, response.reply_text)
