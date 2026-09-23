"""Voice provider abstraction for VarshaDrishti.

Supports Sarvam AI as the primary provider and AI4Bharat IndicConformer
as a local fallback/alternative provider.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]


class VoiceError(Exception):
    """Base exception for voice provider operations."""
    pass


class STTError(VoiceError):
    """Raised when speech-to-text fails."""
    pass


class TTSError(VoiceError):
    """Raised when text-to-speech fails."""
    pass


@dataclass(frozen=True)
class STTResult:
    transcript: str
    language_code: str
    provider: str
    confidence: float | None = None
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class TTSResult:
    audio_bytes: bytes
    content_type: str = "audio/wav"
    provider: str = "sarvam"
    language_code: str = "kn-IN"


def convert_to_16k_wav(input_bytes: bytes, suffix: str = ".webm") -> bytes | None:
    """Convert arbitrary audio bytes (webm, ogg, mp4, etc.) to 16kHz mono WAV via ffmpeg."""
    if not input_bytes or len(input_bytes) < 100:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(input_bytes)
            in_path = f.name
        out_path = in_path + "_16k.wav"
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", in_path, "-ar", "16000", "-ac", "1", out_path],
            capture_output=True,
            timeout=30,
        )
        if os.path.exists(in_path):
            os.unlink(in_path)
        if result.returncode != 0:
            log.error("[VOICE] ffmpeg audio conversion error: %s", result.stderr.decode("utf-8", errors="replace"))
            return None
        with open(out_path, "rb") as out_f:
            wav_bytes = out_f.read()
        if os.path.exists(out_path):
            os.unlink(out_path)
        return wav_bytes
    except Exception as exc:
        log.exception("[VOICE] Audio conversion to WAV failed: %s", exc)
        return None


class VoiceProvider(ABC):
    """Abstract base class for speech-to-text and text-to-speech providers."""

    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the provider is fully configured and ready."""
        pass

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Return provider health and metadata."""
        pass

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, audio_format: str = "webm", lang: str = "kn") -> STTResult:
        """Transcribe speech audio to text."""
        pass

    @abstractmethod
    def synthesize(self, text: str, lang: str = "kn", voice: str | None = None) -> TTSResult:
        """Synthesize text to spoken audio bytes."""
        pass


class SarvamVoiceProvider(VoiceProvider):
    """Sarvam AI speech provider using Saaras STT and Bulbul TTS REST APIs."""

    name = "sarvam"

    STT_URL = "https://api.sarvam.ai/speech-to-text"
    TTS_URL = "https://api.sarvam.ai/text-to-speech"

    # Standard BCP-47 language codes supported by Sarvam
    LANG_MAP = {
        "kn": "kn-IN",
        "hi": "hi-IN",
        "te": "te-IN",
        "en": "en-IN",
        "kn-in": "kn-IN",
        "hi-in": "hi-IN",
        "te-in": "te-IN",
        "en-in": "en-IN",
    }

    SUPPORTED_LANGS = ["kn-IN", "hi-IN", "te-IN", "en-IN"]

    def __init__(
        self,
        api_key: str | None = None,
        stt_model: str | None = None,
        tts_model: str | None = None,
        tts_speaker: str | None = None,
        default_lang: str | None = None,
    ):
        self.api_key = (api_key if api_key is not None else os.environ.get("SARVAM_API_KEY", "")).strip()
        self.stt_model = (stt_model or os.environ.get("SARVAM_STT_MODEL", "saaras:v4")).strip()
        self.tts_model = (tts_model or os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3")).strip()
        self.tts_speaker = (tts_speaker or os.environ.get("SARVAM_TTS_SPEAKER", "shubh")).strip().lower()
        self.default_lang = (default_lang or os.environ.get("SARVAM_STT_LANGUAGE", "kn-IN")).strip()

    def normalize_lang(self, lang: str) -> str:
        code = str(lang or "kn").strip().lower()
        return self.LANG_MAP.get(code, self.LANG_MAP.get(code.split("-")[0], "kn-IN"))

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.is_configured() else "unconfigured",
            "provider": self.name,
            "configured": self.is_configured(),
            "stt_model": self.stt_model,
            "tts_model": self.tts_model,
            "tts_speaker": self.tts_speaker,
            "supported_langs": self.SUPPORTED_LANGS,
        }

    def transcribe(self, audio_bytes: bytes, audio_format: str = "webm", lang: str = "kn") -> STTResult:
        if not self.is_configured():
            raise STTError("SARVAM_API_KEY is not configured on the server.")

        if not audio_bytes or len(audio_bytes) < 100:
            raise STTError("Audio recording is empty or too short.")

        target_lang = self.normalize_lang(lang)
        log.info("[VOICE] STT started (provider: %s, lang: %s, audio size: %d bytes)", self.name, target_lang, len(audio_bytes))
        t0 = time.time()

        # Sarvam STT accepts WAV, MP3, AAC, OGG, OPUS, WebM, etc.
        # Normalize container extension & mime type
        ext = audio_format.lstrip(".").lower()
        if "webm" in ext:
            mime = "audio/webm"
            filename = "recording.webm"
        elif "ogg" in ext:
            mime = "audio/ogg"
            filename = "recording.ogg"
        elif "mp4" in ext:
            mime = "audio/mp4"
            filename = "recording.mp4"
        elif "wav" in ext:
            mime = "audio/wav"
            filename = "recording.wav"
        else:
            mime = "application/octet-stream"
            filename = f"recording.{ext or 'webm'}"

        headers = {
            "api-subscription-key": self.api_key,
        }
        data = {
            "model": self.stt_model,
            "language_code": target_lang,
        }
        files = {
            "file": (filename, io.BytesIO(audio_bytes), mime),
        }

        try:
            resp = requests.post(self.STT_URL, headers=headers, data=data, files=files, timeout=30)
        except requests.exceptions.Timeout:
            log.error("[VOICE] Sarvam STT API timed out after 30 seconds")
            raise STTError("Speech-to-text service timed out. Please try again.")
        except requests.exceptions.RequestException as exc:
            log.error("[VOICE] Sarvam STT network error: %s", exc)
            raise STTError("Network error contacting speech service.")

        duration = time.time() - t0

        if resp.status_code != 200:
            log.error("[VOICE] Sarvam STT returned HTTP %d: %s", resp.status_code, resp.text[:200])
            if resp.status_code in (401, 403):
                raise STTError("Sarvam API authentication failed. Check server credentials.")
            raise STTError(f"Speech recognition failed (HTTP {resp.status_code}).")

        try:
            res_json = resp.json()
        except Exception:
            raise STTError("Invalid response received from speech recognition service.")

        transcript = (res_json.get("transcript") or "").strip()
        log.info("[VOICE] STT completed in %.2fs", duration)
        log.info("[VOICE] Transcript: %s", transcript)

        if not transcript:
            raise STTError("No speech detected. Please speak clearly and try again.")

        return STTResult(
            transcript=transcript,
            language_code=res_json.get("language_code") or target_lang,
            provider=self.name,
            raw_response=res_json,
        )

    def synthesize(self, text: str, lang: str = "kn", voice: str | None = None) -> TTSResult:
        if not self.is_configured():
            raise TTSError("SARVAM_API_KEY is not configured on the server.")

        clean_text = str(text or "").strip()
        if not clean_text:
            raise TTSError("No text provided for speech synthesis.")

        target_lang = self.normalize_lang(lang)
        speaker = (voice or self.tts_speaker).strip().lower()
        log.info("[VOICE] TTS started (provider: %s, lang: %s, speaker: %s, chars: %d)", self.name, target_lang, speaker, len(clean_text))
        t0 = time.time()

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": clean_text,
            "language_code": target_lang,
            "speaker": speaker,
            "model": self.tts_model,
        }

        try:
            resp = requests.post(self.TTS_URL, headers=headers, json=payload, timeout=30)
        except requests.exceptions.Timeout:
            log.error("[VOICE] Sarvam TTS API timed out after 30 seconds")
            raise TTSError("Text-to-speech service timed out.")
        except requests.exceptions.RequestException as exc:
            log.error("[VOICE] Sarvam TTS network error: %s", exc)
            raise TTSError("Network error contacting text-to-speech service.")

        duration = time.time() - t0

        if resp.status_code != 200:
            log.error("[VOICE] Sarvam TTS returned HTTP %d: %s", resp.status_code, resp.text[:200])
            if resp.status_code in (401, 403):
                raise TTSError("Sarvam API authentication failed. Check server credentials.")
            raise TTSError(f"Text-to-speech failed (HTTP {resp.status_code}).")

        try:
            res_json = resp.json()
            audios = res_json.get("audios") or []
            if not audios or not audios[0]:
                raise ValueError("No audio payload in response")
            audio_bytes = base64.b64decode(audios[0])
        except Exception as exc:
            log.error("[VOICE] Failed to decode Sarvam TTS audio response: %s", exc)
            raise TTSError("Could not process synthesized audio response.")

        log.info("[VOICE] TTS completed in %.2fs (audio size: %d bytes)", duration, len(audio_bytes))

        return TTSResult(
            audio_bytes=audio_bytes,
            content_type="audio/wav",
            provider=self.name,
            language_code=target_lang,
        )


class IndicConformerVoiceProvider(VoiceProvider):
    """Retired legacy provider. Replaced by Sarvam AI."""

    name = "indicconformer"

    def is_configured(self) -> bool:
        return False

    def health(self) -> dict[str, Any]:
        return {
            "status": "retired",
            "provider": self.name,
            "configured": False,
            "message": "IndicConformer has been retired. Please use Sarvam AI (VOICE_PROVIDER=sarvam).",
            "supported_langs": [],
        }

    def transcribe(self, audio_bytes: bytes, audio_format: str = "webm", lang: str = "kn") -> STTResult:
        raise STTError("IndicConformer has been retired. Please use Sarvam AI (VOICE_PROVIDER=sarvam).")

    def synthesize(self, text: str, lang: str = "kn", voice: str | None = None) -> TTSResult:
        raise TTSError("Local Parler-TTS has been retired. Please use Sarvam AI (VOICE_PROVIDER=sarvam).")


def get_voice_provider(name: str | None = None) -> VoiceProvider:
    """Return configured voice provider based on environment or explicit name."""
    provider_name = (name or os.environ.get("VOICE_PROVIDER", "sarvam")).strip().lower()
    if provider_name in ("indicconformer", "indic", "conformer", "local"):
        return IndicConformerVoiceProvider()
    return SarvamVoiceProvider()
