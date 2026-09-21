"""Local ASR server using AI4Bharat IndicConformer (600M multilingual).

Run alongside `npm run dev` and `services/tts/server.py` to enable the
farmer voice assistant in the PWA.

    .venv/bin/python services/asr/server.py          # localhost:8766

Endpoints
---------
GET  /health          — 200 OK + {status, model, langs, model_loaded}
POST /transcribe      — multipart/form-data with field 'audio' (webm/wav/ogg)
                        returns JSON {transcript, lang, action, reply_text}

The audio is converted to 16kHz mono WAV via ffmpeg before transcription.
The lang field in the request tells the model which language to decode.
"""
from __future__ import annotations

import cgi
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

PORT = 8766
MODEL_ID = "ai4bharat/indic-conformer-600m-multilingual"
# This checkpoint contains Indic language masks/vocabularies only.  English is
# a UI/TTS language, but passing ``en`` to the model raises KeyError because
# there is no corresponding entry in language_masks.json.
SUPPORTED_LANGS = ["kn", "hi", "te"]
INTERPRET_LANGS = [*SUPPORTED_LANGS, "en"]

# ---------------------------------------------------------------------------
# Intent matching — keyword-based, no LLM needed.
# Each language has a small list of phrases/words that map to actions.
# ---------------------------------------------------------------------------
INTENTS = {
    "rain_yes": {
        "kn": ["ಮಳೆ ಬಂತು", "ಮಳೆ ಬಿತ್ತು", "ಮಳೆ ಆಯಿತು", "ಜೋರು ಮಳೆ", "ಸ್ವಲ್ಪ ಮಳೆ"],
        "hi": ["बारिश हुई", "बारिश आई", "बारिश हो गई", "वर्षा हुई", "थोड़ी बारिश", "तेज बारिश"],
        "te": ["వర్షం పడింది", "వర్షం వచ్చింది", "వర్షం కురిసింది", "కొంచెం వర్షం", "భారీ వర్షం"],
        "en": ["it rained", "rain today", "rained", "there was rain", "heavy rain", "light rain"],
    },
    "rain_no": {
        "kn": ["ಮಳೆ ಇಲ್ಲ", "ಮಳೆ ಬರಲಿಲ್ಲ", "ಮಳೆ ಆಗಲಿಲ್ಲ"],
        "hi": ["बारिश नहीं", "बारिश नहीं हुई", "वर्षा नहीं"],
        "te": ["వర్షం లేదు", "వర్షం పడలేదు", "వర్షం రాలేదు"],
        "en": ["no rain", "did not rain", "no rainfall", "dry"],
    },
    "advisory": {
        "kn": ["ಬಿತ್ತನೆ", "ಸಲಹೆ", "ಏನು ಮಾಡಲಿ", "ಏನು ಮಾಡಬೇಕು", "ಮಾಹಿತಿ"],
        "hi": ["बुवाई", "सलाह", "क्या करूं", "क्या करना", "जानकारी"],
        "te": ["విత్తనాలు", "సలహా", "ఏమి చేయాలి", "సమాచారం"],
        "en": ["sow", "sowing", "advice", "what to do", "advisory", "suggest"],
    },
    "demo_pest": {
        "kn": ["ಬಿಳಿ ಚುಕ್ಕೆ", "ರೋಗ", "ಹುಳು", "white spots", "disease", "pest"],
    },
    "demo_fertilizer": {
        "kn": ["ಯೂರಿಯಾ", "ಗೊಬ್ಬರ", "urea", "fertilizer"],
    },
    "repeat": {
        "kn": ["ಮತ್ತೆ", "ಮತ್ತೊಮ್ಮೆ", "ಮರುಕಳಿಸಿ", "ಮತ್ತೆ ಹೇಳಿ"],
        "hi": ["फिर से", "दोबारा", "फिर बोलो", "दुबारा"],
        "te": ["మళ్ళీ", "మళ్ళీ చెప్పండి", "మరోసారి"],
        "en": ["repeat", "again", "say again", "once more"],
    },
}

REPLIES = {
    "rain_yes": {
        "kn": "ಧನ್ಯವಾದ. ನಿಮ್ಮ ಮಳೆ ವರದಿ ದಾಖಲಾಗಿದೆ.",
        "hi": "धन्यवाद। आपकी बारिश की सूचना दर्ज हो गई।",
        "te": "ధన్యవాదాలు. మీ వర్షం నివేదిక నమోదైంది.",
        "en": "Thank you. Your rain report has been recorded.",
    },
    "rain_no": {
        "kn": "ಧನ್ಯವಾದ. ಮಳೆ ಇಲ್ಲ ಎಂದು ದಾಖಲಾಗಿದೆ.",
        "hi": "धन्यवाद। बारिश नहीं हुई, यह दर्ज हो गया।",
        "te": "ధన్యవాదాలు. వర్షం లేదని నమోదైంది.",
        "en": "Thank you. No rain today has been recorded.",
    },
    "advisory": {
        "kn": "ಇಂದಿನ ಸಲಹೆಗಾಗಿ ಪರದೆಯನ್ನು ನೋಡಿ.",
        "hi": "आज की सलाह खुल गई है। कृपया सुनें बटन दबाएँ।",
        "te": "నేటి సలహా తెరవబడింది. దయచేసి వినండి బటన్ నొక్కండి.",
        "en": "Please check the advice on screen.",
    },
    "repeat": {
        "kn": "ಸಲಹೆ ಮತ್ತೆ ಓದಲಾಗುತ್ತಿದೆ.",
        "hi": "सलाह फिर से पढ़ी जा रही है।",
        "te": "సలహా మళ్ళీ చదవబడుతోంది.",
        "en": "Repeating the advisory now.",
    },
    "demo_pest": {
        "kn": "ಇದು ಬೆಂಕಿ ರೋಗ ಇರಬಹುದು. ಒಂದು ಲೀಟರ್ ನೀರಿಗೆ ಎರಡು ಗ್ರಾಂ ಮ್ಯಾಂಕೋಜೆಬ್ ಬೆರೆಸಿ ಸಿಂಪಡಿಸಿ.",
    },
    "demo_fertilizer": {
        "kn": "ಬಿತ್ತನೆಯಾದ ಮೂವತ್ತು ದಿನಗಳ ನಂತರ, ಮಣ್ಣಿನಲ್ಲಿ ತೇವಾಂಶ ಇದ್ದಾಗ ಎಕರೆಗೆ ಇಪ್ಪತ್ತೈದು ಕೆಜಿ ಯೂರಿಯಾ ಹಾಕಿ.",
    },
    "unknown": {
        "kn": "ಅರ್ಥವಾಗಲಿಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
        "hi": "समझ में नहीं आया। फिर से कोशिश करें।",
        "te": "అర్థం కాలేదు. మళ్ళీ ప్రయత్నించండి.",
        "en": "I didn't understand. Please try again.",
    },
}


def _match_intent(text: str, lang: str) -> str:
    text_lower = text.lower()
    for intent, lang_map in INTENTS.items():
        for phrase in lang_map.get(lang, []):
            if phrase.lower() in text_lower:
                return intent
    return "unknown"


# ---------------------------------------------------------------------------
# Model loading (lazy)
# ---------------------------------------------------------------------------
_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        from transformers import AutoModel
        log.info("Loading IndicConformer from %s ...", MODEL_ID)
        model = AutoModel.from_pretrained(MODEL_ID, trust_remote_code=True)
        _model = model
        log.info("IndicConformer ready.")
        return _model
    except Exception as exc:
        log.error("Failed to load model: %s", exc)
        return None


def _convert_to_wav(input_bytes: bytes, suffix: str = ".webm") -> str | None:
    """Convert any audio bytes to 16kHz mono WAV using ffmpeg. Returns temp WAV path."""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(input_bytes)
            in_path = f.name
        out_path = in_path.replace(suffix, "_16k.wav")
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", in_path, "-ar", "16000", "-ac", "1", out_path],
            capture_output=True, timeout=30,
        )
        os.unlink(in_path)
        if result.returncode != 0:
            log.error("ffmpeg error: %s", result.stderr.decode())
            return None
        return out_path
    except Exception as exc:
        log.exception("Audio conversion failed: %s", exc)
        return None


def _transcribe(wav_path: str, lang: str) -> str | None:
    import torch
    import soundfile as sf
    model = _load_model()
    if model is None:
        return None
    try:
        # Use soundfile directly to bypass torchaudio backend issues
        audio_data, sr = sf.read(wav_path, dtype="float32")
        if audio_data.ndim == 1:
            audio_data = audio_data.reshape(1, -1)
        else:
            audio_data = audio_data.T
        wav = torch.from_numpy(audio_data)

        # Keep this explicit: silently mapping an unsupported language to
        # another language produces confidently wrong transcripts.
        if lang not in SUPPORTED_LANGS:
            log.warning("IndicConformer does not support language %r", lang)
            return None
        lc = lang
        result = model(wav, lc, "ctc")
        return result.strip() if isinstance(result, str) else str(result).strip()
    except Exception as exc:
        log.exception("Transcription failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class ASRHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Lang")

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "model": MODEL_ID,
                "langs": SUPPORTED_LANGS,
                "model_loaded": _model is not None,
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/interpret":
            self._interpret()
            return
        if self.path != "/transcribe":
            self._send_json(404, {"error": "not found"})
            return

        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        # Parse multipart to get audio blob and lang
        lang = self.headers.get("X-Lang", "kn").strip().lower()
        if lang not in SUPPORTED_LANGS:
            self._send_json(400, {
                "error": "unsupported ASR language",
                "lang": lang,
                "supported_langs": SUPPORTED_LANGS,
            })
            return

        # Try to extract audio bytes from multipart
        audio_bytes = None
        suffix = ".webm"
        if "multipart" in content_type:
            boundary = content_type.split("boundary=", 1)[-1].strip().strip('"').encode()
            parts = raw.split(b"--" + boundary)
            for part in parts:
                if b'name="audio"' in part:
                    header_end = part.find(b"\r\n\r\n")
                    header = part[:header_end].lower() if header_end != -1 else part.lower()
                    # Detect the container from the part headers. The browser may
                    # legitimately send Ogg/MP4 instead of WebM (notably Safari).
                    if b"filename=" in header and b".ogg" in header:
                        suffix = ".ogg"
                    elif b"filename=" in header and b".mp4" in header:
                        suffix = ".mp4"
                    elif b"ogg" in header:
                        suffix = ".ogg"
                    elif b"mp4" in header:
                        suffix = ".mp4"
                    elif b"wav" in header:
                        suffix = ".wav"
                    elif b"webm" in header:
                        suffix = ".webm"
                    # Body is after the double CRLF
                    body_start = header_end
                    if body_start != -1:
                        body_start += 4
                        # Remove only the multipart line ending. `rstrip(b"\r\n--")`
                        # treats every listed byte as disposable and can corrupt a
                        # valid audio payload whose final byte happens to match.
                        body_end = part.find(b"\r\n--", body_start)
                        audio_bytes = part[body_start:body_end if body_end != -1 else len(part)]
                    break
        else:
            # Raw binary body (wav/webm posted directly)
            audio_bytes = raw
            suffix = ".wav" if content_type == "audio/wav" else ".webm"

        if not audio_bytes:
            self._send_json(400, {"error": "no audio field in request"})
            return

        log.info("Transcribing [%s] %d bytes %s", lang, len(audio_bytes), suffix)
        wav_path = _convert_to_wav(audio_bytes, suffix)
        if not wav_path:
            self._send_json(500, {"error": "audio conversion failed"})
            return

        transcript = _transcribe(wav_path, lang)
        try:
            os.unlink(wav_path)
        except Exception:
            pass

        if transcript is None:
            self._send_json(503, {"error": "transcription failed"})
            return

        action = _match_intent(transcript, lang)
        reply = REPLIES.get(action, REPLIES["unknown"]).get(lang, REPLIES["unknown"]["en"])

        log.info("Transcript: %r  action: %s  lang: %s", transcript, action, lang)
        self._send_json(200, {
            "transcript": transcript,
            "lang": lang,
            "action": action,
            "reply_text": reply,
        })

    def _interpret(self):
        """Turn browser-provided text into the same action/reply as ASR."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._send_json(400, {"error": "invalid JSON"})
            return

        transcript = (body.get("transcript") or "").strip()
        lang = (body.get("lang") or "kn").strip().lower()
        if not transcript:
            self._send_json(400, {"error": "transcript is required"})
            return
        if lang not in INTERPRET_LANGS:
            self._send_json(400, {
                "error": "unsupported language",
                "lang": lang,
                "supported_langs": INTERPRET_LANGS,
            })
            return

        action = _match_intent(transcript, lang)
        reply = REPLIES.get(action, REPLIES["unknown"]).get(
            lang, REPLIES["unknown"]["en"]
        )
        self._send_json(200, {
            "transcript": transcript,
            "lang": lang,
            "action": action,
            "reply_text": reply,
        })


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        import sys
        if sys.exc_info()[0] is BrokenPipeError:
            return
        super().handle_error(request, client_address)

def main():
    _load_model()
    server = QuietServer(("localhost", PORT), ASRHandler)
    log.info("ASR server listening on http://localhost:%d", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
