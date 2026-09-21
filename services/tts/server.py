"""Local TTS server using Indic Parler-TTS (ai4bharat/indic-parler-tts).

Run alongside `npm run dev` so the Speak button in the PWA gets high-quality
Indic audio instead of the browser's built-in synthesis.

    .venv/bin/python services/tts/server.py

Endpoints
---------
GET  /health          — 200 OK, JSON {status:"ok", model:"...", langs:[...]}
POST /synthesize      — body: {"text":"...", "lang":"kn"|"hi"|"te"|"en"}
                        returns audio/wav

The server loads the model once on startup. All subsequent calls reuse the
loaded pipeline. Run `scripts/tts_setup.py` first to pre-download weights.
"""
from __future__ import annotations

import io
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

PORT = 8765
MODEL_ID = "ai4bharat/indic-parler-tts"

# Natural-language voice prompts — Parler-TTS uses these to control speaker identity.
VOICE = {
    "kn": (
        "Suresh speaks in Kannada at a moderate pace with a clear, warm tone. "
        "The recording has no background noise."
    ),
    "hi": (
        "Rohit speaks in Hindi with a calm and clear voice at a moderate speed. "
        "The recording is clean with no background noise."
    ),
    "te": (
        "Ananya speaks in Telugu with a natural, friendly tone at a moderate pace. "
        "The recording is clean with no background noise."
    ),
    "en": (
        "Meera speaks in English with a clear Indian accent at a moderate pace. "
        "The recording has no background noise."
    ),
}

_pipeline = None


def _load_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    try:
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer
        log.info("Loading Indic Parler-TTS model from %s ...", MODEL_ID)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL_ID).to(device)
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        _pipeline = {"model": model, "tokenizer": tokenizer, "device": device}
        log.info("Model ready on %s", device)
        return _pipeline
    except ImportError as exc:
        log.error("parler-tts or transformers not installed: %s", exc)
        log.error("Run:  pip install -r services/tts/requirements.txt")
        return None


def _synthesize(text: str, lang: str) -> bytes | None:
    pipe = _load_pipeline()
    if pipe is None:
        return None
    try:
        import torch
        import soundfile as sf
        model = pipe["model"]
        tokenizer = pipe["tokenizer"]
        device = pipe["device"]

        prompt = VOICE.get(lang, VOICE["en"])
        desc_ids = tokenizer(prompt, return_tensors="pt").input_ids.to(device)
        text_ids = tokenizer(text, return_tensors="pt").input_ids.to(device)

        with torch.no_grad():
            generation = model.generate(input_ids=desc_ids, prompt_input_ids=text_ids)

        audio = generation.cpu().numpy().squeeze()
        sample_rate = model.config.sampling_rate

        buf = io.BytesIO()
        sf.write(buf, audio, sample_rate, format="WAV")
        buf.seek(0)
        return buf.read()
    except Exception as exc:
        log.exception("Synthesis failed: %s", exc)
        return None


class TTSHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_wav(self, data: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "model": MODEL_ID,
                "langs": list(VOICE.keys()),
                "model_loaded": _pipeline is not None,
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/synthesize":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._send_json(400, {"error": "invalid JSON"})
            return
        text = (body.get("text") or "").strip()
        lang = (body.get("lang") or "kn").strip()
        if not text:
            self._send_json(400, {"error": "text is required"})
            return
        if lang not in VOICE:
            self._send_json(400, {"error": f"lang must be one of {list(VOICE)}"})
            return
        log.info("Synthesising [%s] %d chars", lang, len(text))
        wav = _synthesize(text, lang)
        if wav is None:
            self._send_json(503, {"error": "synthesis failed — check server logs"})
            return
        self._send_wav(wav)


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        import sys
        if sys.exc_info()[0] is BrokenPipeError:
            return
        super().handle_error(request, client_address)

def main():
    _load_pipeline()
    server = QuietServer(("localhost", PORT), TTSHandler)
    log.info("TTS server listening on http://localhost:%d", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
