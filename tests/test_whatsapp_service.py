"""Automated Test Suite for VarshaDrishti Farmer WhatsApp Assistant & Proactive Alerts.

Covers all 9 operational and resilience scenarios:
1. Incoming text forecast Q&A
2. Incoming Kannada voice note (STT -> forecast -> TTS -> PTT audio)
3. Dynamic location change (Hobli A -> Hobli B)
4. Scheduled 6:00 AM morning briefing
5. Threshold crossing alert & anti-spam deduplication
6. Sub-threshold stability (no spurious alerts)
7. Sarvam API failure resilience (graceful text fallback)
8. Forecast unavailability resilience (truthful error, no hallucination)
9. Unknown farmer location prompt (no guessing)
"""
from __future__ import annotations

import io
import json
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pytest

from services.voice.providers import (
    STTError,
    STTResult,
    TTSError,
    TTSResult,
    VoiceProvider,
    convert_wav_to_opus_ogg,
)
from services.whatsapp.alert_engine import (
    HEAVY_RAIN_THRESHOLD,
    build_farmer_alert,
    build_morning_briefing,
    dispatch_morning_briefings,
    dispatch_proactive_alerts,
    evaluate_area_alerts,
    is_alert_already_sent,
)
from services.whatsapp.mock_backend import MockWhatsAppBackend
from services.whatsapp.service import (
    WhatsAppService,
    normalize_phone,
)

ROOT = Path(__file__).resolve().parents[1]


def create_dummy_wav() -> bytes:
    """Generate a tiny valid 16kHz mono WAV in memory."""
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 8000)  # 0.5s silence
    return bio.getvalue()


class MockVoiceProvider(VoiceProvider):
    """Controllable voice provider mock for deterministic testing."""

    name = "mock_sarvam"

    def __init__(self, should_fail_stt: bool = False, should_fail_tts: bool = False) -> None:
        self.should_fail_stt = should_fail_stt
        self.should_fail_tts = should_fail_tts
        self.transcribe_calls: list[tuple[bytes, str, str]] = []
        self.synthesize_calls: list[tuple[str, str]] = []

    def is_configured(self) -> bool:
        return True

    def health(self) -> dict:
        return {"status": "ok", "provider": self.name}

    def transcribe(self, audio_bytes: bytes, audio_format: str = "webm", lang: str = "kn") -> STTResult:
        self.transcribe_calls.append((audio_bytes, audio_format, lang))
        if self.should_fail_stt:
            raise STTError("Sarvam STT HTTP 500: Internal Server Error")
        return STTResult(
            transcript="ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?",
            language_code="kn-IN",
            provider=self.name,
        )

    def synthesize(self, text: str, lang: str = "kn", voice: str | None = None) -> TTSResult:
        self.synthesize_calls.append((text, lang))
        if self.should_fail_tts:
            raise TTSError("Sarvam TTS connection timed out")
        wav_bytes = create_dummy_wav()
        return TTSResult(
            audio_bytes=wav_bytes,
            content_type="audio/wav",
            provider=self.name,
            language_code="kn-IN",
        )


@pytest.fixture
def mock_backend() -> MockWhatsAppBackend:
    return MockWhatsAppBackend()


@pytest.fixture(autouse=True)
def in_memory_store(monkeypatch):
    """Isolate notification store in-memory for deterministic, idempotent test runs."""
    records = []

    def mock_record(row):
        r = {"created_at": datetime.now(timezone.utc).isoformat(), **row}
        records.append(r)
        return r, "memory"

    def mock_recent(area_id=None, limit=100):
        filtered = [r for r in records if not area_id or r.get("area_id") == area_id]
        return filtered, "memory"

    monkeypatch.setattr("services.whatsapp.alert_engine.store.record", mock_record)
    monkeypatch.setattr("services.whatsapp.alert_engine.store.recent", mock_recent)
    return records


@pytest.fixture
def voice_provider() -> MockVoiceProvider:
    return MockVoiceProvider()


@pytest.fixture
def service(mock_backend: MockWhatsAppBackend, voice_provider: MockVoiceProvider) -> WhatsAppService:
    svc = WhatsAppService(backend=mock_backend, voice_provider=voice_provider)
    # Ensure fresh test farmer
    svc.update_farmer_location(
        phone="919876543210",
        area_id="KGIS-H-010901",  # Bailahongala
        lang="kn",
        name="Basavaraj",
    )
    return svc


# --- Test 1: Incoming Text Forecast Q&A ---------------------------------------

def test_1_incoming_text_grounded_answer(service: WhatsAppService, mock_backend: MockWhatsAppBackend):
    """Test 1: Registered farmer texts weather question -> receives grounded Bailahongala answer."""
    resp = service.handle_incoming_text("919876543210", "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?")
    service.dispatch_reply("919876543210", resp)

    assert resp.intent == "rain_tomorrow"
    # Grounded in Bailahongala's forecast data
    assert "Bailahongala" in resp.reply_text or "ಬೈಲಹೊಂಗಲ" in resp.reply_text
    assert "ಮಳೆ" in resp.reply_text

    # Verify message was dispatched via backend
    sent = mock_backend.get_last_text("919876543210")
    assert sent is not None
    assert sent.text == resp.reply_text


# --- Test 2: Incoming Kannada Voice Note --------------------------------------

def test_2_incoming_kannada_voice_message(service: WhatsAppService, mock_backend: MockWhatsAppBackend, voice_provider: MockVoiceProvider):
    """Test 2: Farmer sends voice note -> Sarvam STT -> Grounded forecast -> Sarvam TTS -> WhatsApp voice reply."""
    dummy_audio = create_dummy_wav()
    resp = service.handle_incoming_audio("919876543210", dummy_audio, mime_type="audio/ogg")
    service.dispatch_reply("919876543210", resp)

    assert len(voice_provider.transcribe_calls) == 1
    assert len(voice_provider.synthesize_calls) == 1
    assert resp.intent == "rain_tomorrow"
    assert resp.reply_audio is not None
    # Verify audio is Opus OGG
    assert resp.reply_audio[:4] == b"OggS"

    # Verify voice message dispatched via backend
    voice_msg = mock_backend.get_last_voice("919876543210")
    assert voice_msg is not None
    assert voice_msg.audio_bytes == resp.reply_audio
    assert voice_msg.is_ptt is True


# --- Test 3: Dynamic Location Change ------------------------------------------

def test_3_dynamic_location_change(service: WhatsAppService, mock_backend: MockWhatsAppBackend):
    """Test 3: Changing farmer location from Hobli A to Hobli B switches forecast grounding dynamically."""
    # Step 1: Farmer registered at Bailahongala
    resp1 = service.handle_incoming_text("919876543210", "ಈ ವಾರ ಮಳೆ ಹೇಗಿರುತ್ತದೆ?")
    assert "Bailahongala" in resp1.reply_text or "ಬೈಲಹೊಂಗಲ" in resp1.reply_text

    # Step 2: Farmer updates location to Kasaba, Tumakuru (KGIS-H-180901)
    update_resp = service.handle_incoming_text("919876543210", "change location to KGIS-H-180901")
    assert update_resp.intent == "location_updated"
    assert update_resp.grounding_data.get("area_id") == "KGIS-H-180901"

    # Step 3: Next question is grounded in Kasaba, NOT Bailahongala
    resp2 = service.handle_incoming_text("919876543210", "ಈ ವಾರ ಮಳೆ ಹೇಗಿರುತ್ತದೆ?")
    assert "Bailahongala" not in resp2.reply_text
    assert "Kasaba" in resp2.reply_text or "ಕಸಬಾ" in resp2.reply_text


# --- Test 4: Scheduled 6:00 AM Morning Briefing -------------------------------

def test_4_morning_briefing_dispatch(mock_backend: MockWhatsAppBackend, voice_provider: MockVoiceProvider):
    """Test 4: Simulates 6:00 AM morning briefing dispatched to registered farmer."""
    subscriber = {
        "destination": "919876543210",
        "area_id": "KGIS-H-010901",
        "lang": "kn",
        "channel": "whatsapp",
        "active": True,
    }
    # Clear any previous test notification records for clean state
    dispatched = dispatch_morning_briefings(
        backend=mock_backend,
        subscribers=[subscriber],
        voice_provider=voice_provider,
    )
    assert len(dispatched) >= 1
    assert dispatched[0]["area_id"] == "KGIS-H-010901"
    assert dispatched[0]["risk_event"] == "morning_briefing"

    # Verify voice & text both sent
    assert mock_backend.get_last_text("919876543210") is not None
    assert mock_backend.get_last_voice("919876543210") is not None


# --- Test 5: Threshold Crossing & Deduplication --------------------------------

def test_5_threshold_alert_and_deduplication(mock_backend: MockWhatsAppBackend, voice_provider: MockVoiceProvider):
    """Test 5: Alert crosses threshold -> Sent. Re-running job on same day -> Deduplicated & suppressed."""
    mock_backend.clear()
    subscriber = {
        "destination": "919123456789",
        "area_id": "KGIS-H-010901",
        "lang": "kn",
        "channel": "whatsapp",
        "active": True,
    }

    # Run dispatch for the first time
    first_run = dispatch_proactive_alerts(
        backend=mock_backend,
        subscribers=[subscriber],
        voice_provider=voice_provider,
    )
    first_count = len(first_run)
    assert first_count >= 1, "Expected at least one proactive alert for Bailahongala (severe_dry_spell or delay)"

    # Run dispatch a second time on the same day -> Must deduplicate
    mock_backend.clear()
    second_run = dispatch_proactive_alerts(
        backend=mock_backend,
        subscribers=[subscriber],
        voice_provider=voice_provider,
    )
    assert len(second_run) == 0, "Second run must be deduplicated and produce 0 dispatches"
    assert len(mock_backend.sent_texts) == 0


# --- Test 6: Sub-threshold Stability (No Spurious Alerts) ---------------------

def test_6_sub_threshold_stability():
    """Test 6: Area with low risks below thresholds generates 0 alerts."""
    # Mock area with very low dry risk and low heavy rain risk
    with patch("services.whatsapp.alert_engine.load_forecast_for_area") as mock_load:
        mock_load.return_value = {
            "forecast": {
                "area_id": "TEST-CALM",
                "name_en": "Calm Hobli",
                "p_heavy": {"w1": 0.05},
                "p_dry7": {"w1": 0.10},
                "onset_delay_weeks": 0.0,
            }
        }
        alerts = evaluate_area_alerts("TEST-CALM")
        assert len(alerts) == 0, f"Expected 0 alerts for calm weather, got {alerts}"


# --- Test 7: Sarvam Failure Resilience (Graceful Text Fallback) ---------------

def test_7_sarvam_failure_resilience(mock_backend: MockWhatsAppBackend):
    """Test 7: Sarvam API 500 error during STT or TTS does not crash system, returns text fallback."""
    # STT Failure
    failing_stt_provider = MockVoiceProvider(should_fail_stt=True)
    svc1 = WhatsAppService(backend=mock_backend, voice_provider=failing_stt_provider)
    resp1 = svc1.handle_incoming_audio("919876543210", create_dummy_wav())
    assert resp1.intent == "stt_failed"
    assert "ಧ್ವನಿ ಸಂದೇಶವನ್ನು ಪ್ರಕ್ರಿಯೆಗೊಳಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ" in resp1.reply_text

    # TTS Failure: STT succeeds but TTS fails -> system delivers text reply without audio
    failing_tts_provider = MockVoiceProvider(should_fail_tts=True)
    svc2 = WhatsAppService(backend=mock_backend, voice_provider=failing_tts_provider)
    resp2 = svc2.handle_incoming_audio("919876543210", create_dummy_wav())
    assert resp2.intent == "rain_tomorrow"
    assert resp2.reply_audio is None  # Gracefully fell back to text-only
    assert len(resp2.reply_text) > 0


# --- Test 8: Forecast Failure Resilience (Truthful Reporting) -----------------

def test_8_forecast_failure_resilience(service: WhatsAppService):
    """Test 8: If forecast data for an area is missing, report unavailable rather than hallucinating."""
    resp = service.handle_incoming_text("919876543210", "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?")
    
    # Query with a non-existent hobli ID
    with patch("services.voice.assistant.load_forecast_for_area", return_value=None):
        resp_missing = service.handle_incoming_text("919876543210", "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?")
        assert resp_missing.intent == "forecast_unavailable"
        assert "ಲಭ್ಯವಿಲ್ಲ" in resp_missing.reply_text or "unavailable" in resp_missing.reply_text.lower()


# --- Test 9: Unknown Farmer Location Prompt (No Guessing) ---------------------

def test_9_unknown_farmer_location_prompt(mock_backend: MockWhatsAppBackend, voice_provider: MockVoiceProvider):
    """Test 9: Unregistered phone asking a weather question is prompted for hobli name without guessing."""
    svc = WhatsAppService(backend=mock_backend, voice_provider=voice_provider)
    unknown_phone = "919000000001"
    
    resp = svc.handle_incoming_text(unknown_phone, "Will it rain tomorrow?")
    assert resp.intent == "missing_location"
    assert "ಹೋಬಳಿ" in resp.reply_text or "hobli" in resp.reply_text.lower()
