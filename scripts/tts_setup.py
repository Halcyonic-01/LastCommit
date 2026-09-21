"""Download and verify Indic Parler-TTS for all four languages.

    .venv/bin/python scripts/tts_setup.py

Downloads model weights (~1.5 GB, cached in ~/.cache/huggingface/hub) and
synthesises one test sentence per language, saving the result to audio/test/.
Prints PASS/FAIL per language so you can play each file and verify quality.
"""
import sys
import json
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio" / "test"
MODEL_ID = "ai4bharat/indic-parler-tts"

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

# One representative advisory sentence per language
TEST_TEXT = {
    "kn": "ಈ ವಾರ ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಕಡಿಮೆ. ಈಗ ಬಿತ್ತನೆ ಮಾಡಬೇಡಿ.",
    "hi": "इस हफ़्ते बारिश की उम्मीद कम है। अभी बुवाई न करें।",
    "te": "ఈ వారం వర్షం వచ్చే అవకాశం తక్కువ. ఇప్పుడు విత్తనం వేయవద్దు.",
    "en": "Little chance of rain this week. Do not sow yet.",
}


def main():
    try:
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer
        import soundfile as sf
    except ImportError as exc:
        sys.exit(
            f"Missing dependency: {exc}\n"
            "Run:  pip install -r services/tts/requirements.txt"
        )

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Loading model {MODEL_ID} (downloads weights on first run) ...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL_ID).to(device)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    sample_rate = model.config.sampling_rate
    print(f"Model loaded. Sample rate: {sample_rate} Hz\n")

    results = {}
    for lang, text in TEST_TEXT.items():
        print(f"[{lang}] Synthesising: {text[:60]}...")
        try:
            desc_ids = tokenizer(VOICE[lang], return_tensors="pt").input_ids.to(device)
            text_ids = tokenizer(text, return_tensors="pt").input_ids.to(device)
            with torch.no_grad():
                gen = model.generate(input_ids=desc_ids, prompt_input_ids=text_ids)
            audio = gen.cpu().numpy().squeeze()
            out = AUDIO_DIR / f"test_{lang}.wav"
            sf.write(str(out), audio, sample_rate)
            dur = len(audio) / sample_rate
            results[lang] = {"status": "PASS", "file": str(out), "duration_s": round(dur, 2)}
            print(f"  PASS — {out.name} ({dur:.1f}s)")
        except Exception as exc:
            results[lang] = {"status": "FAIL", "error": str(exc)}
            print(f"  FAIL — {exc}")

    print("\n--- Summary ---")
    for lang, r in results.items():
        print(f"  {lang}: {r['status']}", end="")
        if r["status"] == "PASS":
            print(f" → {r['file']} ({r['duration_s']}s)")
        else:
            print(f" → {r.get('error')}")

    failed = [l for l, r in results.items() if r["status"] != "PASS"]
    if failed:
        print(f"\nFailed languages: {failed}")
        return 1
    print("\nAll languages OK. Play the files in audio/test/ to verify quality.")
    print("Start the server with:  .venv/bin/python services/tts/server.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
