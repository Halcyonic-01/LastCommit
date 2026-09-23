"""Voice assistant HTTP server for VarshaDrishti.

Integrates Sarvam AI (primary) and AI4Bharat IndicConformer (fallback),
connected to the grounded VarshaDrishti assistant logic.

Usage:
    .venv/bin/python services/voice/server.py       # runs on http://localhost:8766

Endpoints:
    GET  /health          — 200 OK + provider status, configuration, models
    POST /transcribe      — multipart with 'audio' (+ optional X-Lang, X-Area-Id)
                            Returns JSON: {transcript, lang, action, reply_text, audio_base64}
    POST /interpret       — JSON: {transcript, lang, area_id} -> {transcript, lang, action, reply_text}
    POST /synthesize      — JSON: {text, lang, speaker} -> audio/wav bytes
    POST /api/test/stt    — Developer endpoint: audio -> transcript
    POST /api/test/tts    — Developer endpoint: text -> audio
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services"))

from services.voice.assistant import generate_grounded_answer, load_forecast_for_area
from services.voice.narration import build_today_narration, build_why_narration
from services.voice.providers import (
    STTError,
    TTSError,
    VoiceError,
    convert_to_16k_wav,
    get_voice_provider,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

PORT = int(os.environ.get("VOICE_PORT", os.environ.get("ASR_PORT", "8766")))
HOST = os.environ.get("VOICE_HOST", "0.0.0.0")

AUDIO_CACHE_DIR = ROOT / "data" / "cache" / "audio"
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _audio_cache_path(provider_name: str, lang: str, text: str, voice: str | None = None) -> Path:
    """Deterministic hash path for cached TTS audio."""
    key_str = f"{provider_name}:{voice or 'default'}:{lang}:{text.strip()}"
    h = hashlib.sha256(key_str.encode("utf-8")).hexdigest()
    return AUDIO_CACHE_DIR / f"{h}.wav"


def load_env():
    """Load key-value pairs from .env if present without overriding existing environment."""
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()


class VoiceHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for VarshaDrishti Voice Services."""

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Lang, X-Area-Id, Accept")

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_wav(self, data: bytes, hit: bool = False, extra_headers: dict[str, str] | None = None):
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=2592000, immutable")
        self.send_header("X-Cache", "HIT" if hit else "MISS")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        clean_path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        if clean_path in ("/health", "/api/health"):
            provider = get_voice_provider()
            health_info = provider.health()
            self._send_json(200, {
                "status": "ok",
                "provider": provider.name,
                "configured": provider.is_configured(),
                "details": health_info,
                "langs": ["kn", "hi", "te", "en"],
            })
        elif clean_path == "/api/narration":
            self._handle_get_narration(query)
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_get_narration(self, query: dict[str, list[str]]):
        area_id = (query.get("area_id", ["KGIS-H-180901"])[0]).strip()
        screen = (query.get("screen", ["today"])[0]).strip().lower()
        lang = (query.get("lang", ["kn"])[0]).strip().lower()

        forecast_data = load_forecast_for_area(area_id)
        if not forecast_data:
            self._send_json(404, {"error": f"Forecast for area {area_id} not found"})
            return

        if screen == "why":
            text = build_why_narration(forecast_data, lang=lang)
        else:
            text = build_today_narration(forecast_data, lang=lang)

        provider = get_voice_provider()
        cache_file = _audio_cache_path(provider.name, lang, text)
        safe_header = urllib.parse.quote(text)

        if cache_file.exists():
            log.info("[VOICE] Serving narration from cache for area=%s, screen=%s, lang=%s", area_id, screen, lang)
            data = cache_file.read_bytes()
            self._send_wav(data, hit=True, extra_headers={"X-Narration-Text": safe_header})
            return

        if not provider.is_configured():
            self._send_json(503, {"error": "Voice provider not configured"})
            return

        try:
            log.info("[VOICE] Synthesizing narration for area=%s, screen=%s, lang=%s", area_id, screen, lang)
            tts_res = provider.synthesize(text, lang=lang)
            try:
                cache_file.write_bytes(tts_res.audio_bytes)
            except Exception as e:
                log.warning("[VOICE] Could not cache narration: %s", e)
            self._send_wav(tts_res.audio_bytes, hit=False, extra_headers={"X-Narration-Text": safe_header})
        except Exception as exc:
            log.exception("[VOICE] Narration synthesis failed: %s", exc)
            self._send_json(500, {"error": f"Narration synthesis failed: {exc}"})

    def _extract_audio_payload(self) -> tuple[bytes | None, str, str, str]:
        """Extract (audio_bytes, suffix, lang, area_id) from POST request."""
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        lang = self.headers.get("X-Lang", "").strip().lower() or "kn"
        area_id = self.headers.get("X-Area-Id", "").strip() or "KGIS-H-180901"

        suffix = ".webm"
        audio_bytes = None

        if "multipart" in content_type:
            boundary = content_type.split("boundary=", 1)[-1].strip().strip('"').encode()
            parts = raw.split(b"--" + boundary)
            for part in parts:
                # Check for metadata fields inside multipart
                if b'name="lang"' in part:
                    h_end = part.find(b"\r\n\r\n")
                    if h_end != -1:
                        val = part[h_end + 4 : part.find(b"\r\n--", h_end + 4)].decode("utf-8", errors="ignore").strip()
                        if val:
                            lang = val
                if b'name="area_id"' in part or b'name="areaId"' in part:
                    h_end = part.find(b"\r\n\r\n")
                    if h_end != -1:
                        val = part[h_end + 4 : part.find(b"\r\n--", h_end + 4)].decode("utf-8", errors="ignore").strip()
                        if val:
                            area_id = val

                if b'name="audio"' in part or b'name="file"' in part:
                    h_end = part.find(b"\r\n\r\n")
                    header = part[:h_end].lower() if h_end != -1 else part.lower()
                    if b"filename=" in header and b".ogg" in header:
                        suffix = ".ogg"
                    elif b"filename=" in header and b".mp4" in header:
                        suffix = ".mp4"
                    elif b"filename=" in header and b".wav" in header:
                        suffix = ".wav"
                    elif b"ogg" in header:
                        suffix = ".ogg"
                    elif b"mp4" in header:
                        suffix = ".mp4"
                    elif b"wav" in header:
                        suffix = ".wav"
                    elif b"webm" in header:
                        suffix = ".webm"

                    body_start = h_end + 4 if h_end != -1 else -1
                    if body_start != -1:
                        body_end = part.find(b"\r\n--", body_start)
                        audio_bytes = part[body_start : body_end if body_end != -1 else len(part)]
        else:
            audio_bytes = raw
            suffix = ".wav" if "wav" in content_type else ".webm"

        return audio_bytes, suffix, lang, area_id

    def do_POST(self):
        clean_path = self.path.split("?")[0].rstrip("/")

        if clean_path == "/interpret":
            self._handle_interpret()
            return

        if clean_path == "/synthesize":
            self._handle_synthesize()
            return

        if clean_path == "/api/test/stt":
            self._handle_test_stt()
            return

        if clean_path == "/api/test/tts":
            self._handle_test_tts()
            return

        if clean_path in ("/transcribe", "/voice-assistant"):
            self._handle_voice_assistant()
            return

        self._send_json(404, {"error": "not found"})

    def _handle_voice_assistant(self):
        """End-to-end voice assistant flow: Audio -> STT -> Grounded Assistant -> TTS -> Response."""
        audio_bytes, suffix, lang, area_id = self._extract_audio_payload()

        if not audio_bytes or len(audio_bytes) < 100:
            self._send_json(400, {
                "error": "Audio recording is empty or too short. Please hold the button and speak.",
                "code": "empty_audio",
            })
            return

        log.info("[VOICE] Recording received (size: %d bytes, format: %s, lang: %s, area: %s)", len(audio_bytes), suffix, lang, area_id)

        provider = get_voice_provider()
        if not provider.is_configured():
            log.error("[VOICE] Active provider %s is not configured (missing credentials)", provider.name)
            self._send_json(503, {
                "error": f"Voice provider '{provider.name}' is not configured on the server.",
                "code": "unconfigured_provider",
            })
            return

        # 1. Speech-to-Text
        try:
            stt_result = provider.transcribe(audio_bytes, audio_format=suffix, lang=lang)
            transcript = stt_result.transcript
        except STTError as exc:
            log.warning("[VOICE] STT failed: %s", exc)
            self._send_json(400, {
                "error": str(exc),
                "code": "stt_failed",
            })
            return
        except Exception as exc:
            log.exception("[VOICE] Unexpected error during STT: %s", exc)
            self._send_json(500, {
                "error": "Failed to process speech. Please try again.",
                "code": "stt_error",
            })
            return

        if not transcript:
            self._send_json(400, {
                "error": "I could not hear a clear answer. Please try again.",
                "code": "empty_transcript",
            })
            return

        # 2. Grounded VarshaDrishti Assistant
        assistant_res = generate_grounded_answer(transcript, lang=lang, area_id=area_id)
        reply_text = assistant_res["reply_text"]
        action = assistant_res["action"]
        log.info("[VOICE] Assistant response generated (action: %s)", action)

        # 3. Text-to-Speech (with disk cache)
        audio_b64 = None
        tts_error_msg = None
        cache_file = _audio_cache_path(provider.name, lang, reply_text)
        if cache_file.exists():
            log.info("[VOICE] Assistant response audio loaded from cache (%s)", cache_file.name)
            try:
                audio_b64 = base64.b64encode(cache_file.read_bytes()).decode("ascii")
            except Exception as e:
                log.warning("[VOICE] Error reading cached audio: %s", e)

        if not audio_b64:
            try:
                tts_result = provider.synthesize(reply_text, lang=lang)
                audio_b64 = base64.b64encode(tts_result.audio_bytes).decode("ascii")
                try:
                    cache_file.write_bytes(tts_result.audio_bytes)
                except Exception as e:
                    log.warning("[VOICE] Could not cache assistant audio: %s", e)
            except TTSError as exc:
                log.warning("[VOICE] TTS failed: %s (will return text answer without audio)", exc)
                tts_error_msg = str(exc)
            except Exception as exc:
                log.exception("[VOICE] Unexpected error during TTS: %s", exc)
                tts_error_msg = "Audio synthesis failed"

        # Return full response to browser
        self._send_json(200, {
            "transcript": transcript,
            "lang": lang,
            "action": action,
            "reply_text": reply_text,
            "audio_base64": audio_b64,
            "audio_format": "audio/wav",
            "provider": provider.name,
            "grounding": assistant_res.get("grounding_data", {}),
            "tts_error": tts_error_msg,
        })

    def _handle_interpret(self):
        """Interpret browser text directly into an agricultural action & reply."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._send_json(400, {"error": "invalid JSON"})
            return

        transcript = (body.get("transcript") or "").strip()
        lang = (body.get("lang") or "kn").strip().lower()
        area_id = (body.get("area_id") or body.get("areaId") or "KGIS-H-180901").strip()

        if not transcript:
            self._send_json(400, {"error": "transcript is required"})
            return

        assistant_res = generate_grounded_answer(transcript, lang=lang, area_id=area_id)
        self._send_json(200, {
            "transcript": transcript,
            "lang": lang,
            "action": assistant_res["action"],
            "reply_text": assistant_res["reply_text"],
            "grounding": assistant_res.get("grounding_data", {}),
        })

    def _handle_synthesize(self):
        """Synthesize text to audio with server-side caching."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._send_json(400, {"error": "invalid JSON"})
            return

        text = (body.get("text") or "").strip()
        lang = (body.get("lang") or "kn").strip().lower()
        speaker = body.get("speaker") or body.get("voice")

        if not text:
            self._send_json(400, {"error": "text is required"})
            return

        provider = get_voice_provider()
        cache_file = _audio_cache_path(provider.name, lang, text, voice=speaker)
        accept = self.headers.get("Accept", "")

        # Check disk cache first
        if cache_file.exists():
            log.info("[VOICE] Serving synthesize audio from cache (%s)", cache_file.name)
            cached_bytes = cache_file.read_bytes()
            if "application/json" in accept:
                self._send_json(200, {
                    "audio_base64": base64.b64encode(cached_bytes).decode("ascii"),
                    "format": "audio/wav",
                    "provider": provider.name,
                    "cached": True,
                })
            else:
                self._send_wav(cached_bytes, hit=True)
            return

        if not provider.is_configured():
            self._send_json(503, {"error": f"Voice provider '{provider.name}' is not configured."})
            return

        try:
            tts_res = provider.synthesize(text, lang=lang, voice=speaker)
            try:
                cache_file.write_bytes(tts_res.audio_bytes)
            except Exception as e:
                log.warning("[VOICE] Could not cache synthesized audio: %s", e)

            if "application/json" in accept:
                self._send_json(200, {
                    "audio_base64": base64.b64encode(tts_res.audio_bytes).decode("ascii"),
                    "format": "audio/wav",
                    "provider": provider.name,
                    "cached": False,
                })
            else:
                self._send_wav(tts_res.audio_bytes, hit=False)
        except TTSError as exc:
            self._send_json(503, {"error": str(exc)})
        except Exception as exc:
            log.exception("[VOICE] Error synthesizing text: %s", exc)
            self._send_json(500, {"error": "Synthesis failed."})

    def _handle_test_stt(self):
        """Developer test endpoint: Audio -> STT -> Transcript."""
        audio_bytes, suffix, lang, _ = self._extract_audio_payload()
        if not audio_bytes or len(audio_bytes) < 100:
            self._send_json(400, {"error": "audio payload missing or too short"})
            return

        provider = get_voice_provider()
        if not provider.is_configured():
            self._send_json(503, {"error": f"Provider '{provider.name}' is not configured."})
            return

        try:
            res = provider.transcribe(audio_bytes, audio_format=suffix, lang=lang)
            self._send_json(200, {
                "status": "ok",
                "provider": provider.name,
                "transcript": res.transcript,
                "language_code": res.language_code,
            })
        except Exception as exc:
            self._send_json(500, {"status": "error", "error": str(exc)})

    def _handle_test_tts(self):
        """Developer test endpoint: Text -> TTS -> playable audio."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._send_json(400, {"error": "invalid JSON"})
            return

        text = (body.get("text") or "ನಮಸ್ಕಾರ, ವರ್ಷದೃಷ್ಟಿಗೆ ಸ್ವಾಗತ.").strip()
        lang = (body.get("lang") or "kn").strip()
        provider = get_voice_provider()

        if not provider.is_configured():
            self._send_json(503, {"error": f"Provider '{provider.name}' is not configured."})
            return

        try:
            res = provider.synthesize(text, lang=lang)
            accept = self.headers.get("Accept", "")
            if "audio" in accept:
                self._send_wav(res.audio_bytes)
            else:
                self._send_json(200, {
                    "status": "ok",
                    "provider": provider.name,
                    "text": text,
                    "lang": lang,
                    "size_bytes": len(res.audio_bytes),
                    "audio_base64": base64.b64encode(res.audio_bytes).decode("ascii"),
                })
        except Exception as exc:
            self._send_json(500, {"status": "error", "error": str(exc)})


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        if sys.exc_info()[0] is BrokenPipeError:
            return
        super().handle_error(request, client_address)


def main():
    provider = get_voice_provider()
    log.info("[VOICE] Starting VarshaDrishti Voice Server on http://%s:%d", HOST, PORT)
    log.info("[VOICE] Active Voice Provider: %s (configured: %s)", provider.name, provider.is_configured())

    server = QuietServer((HOST, PORT), VoiceHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("[VOICE] Server shutting down.")
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
