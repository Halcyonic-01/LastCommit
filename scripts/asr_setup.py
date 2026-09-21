"""Download and verify IndicConformer ASR for the supported languages.

    .venv/bin/python scripts/asr_setup.py

Downloads model weights (~1.2 GB, cached in ~/.cache/huggingface/hub),
synthesises a short test WAV for each language using a 1-second tone,
then transcribes it to verify the pipeline is working end-to-end.
"""
import sys
import subprocess
import tempfile
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_ID = "ai4bharat/indic-conformer-600m-multilingual"

TEST_PHRASES = {
    "kn": "ಮಳೆ ಬಂತು",
    "hi": "बारिश हुई",
    "te": "వర్షం పడింది",
}


def _check_ffmpeg():
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def main():
    print("=== IndicConformer ASR Setup ===\n")

    if not _check_ffmpeg():
        sys.exit("ERROR: ffmpeg not found. Install with: brew install ffmpeg")
    print("ffmpeg: OK")

    try:
        import torch
        import torchaudio
        from transformers import AutoModel
    except ImportError as exc:
        sys.exit(f"Missing dependency: {exc}\nRun: pip install -r services/asr/requirements.txt")

    print(f"\nLoading model {MODEL_ID} (downloads ~1.2 GB on first run) ...")
    try:
        model = AutoModel.from_pretrained(MODEL_ID, trust_remote_code=True)
        print("Model loaded OK\n")
    except Exception as exc:
        sys.exit(
            f"Could not load model: {exc}\n"
            "Make sure you are logged in to HuggingFace and have accepted the model terms at:\n"
            "  https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual"
        )

    # Generate a 1-second 440Hz tone WAV as a dummy audio file to test the pipeline
    import soundfile as sf
    import numpy as np

    results = {}
    print("Testing transcription pipeline (tone audio — expect garbage output, just checking no crash):")
    # The IndicConformer checkpoint does not contain an English vocabulary.
    for lang in ["kn", "hi", "te"]:
        try:
            tone = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 16000)).astype("float32")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                sf.write(f.name, tone, 16000)
                wav_path = f.name
            wav_np, sr = sf.read(wav_path, dtype="float32")
            import torch
            wav = torch.from_numpy(wav_np).reshape(1, -1)
            os.unlink(wav_path)
            out = model(wav, lang, "ctc")
            results[lang] = {"status": "PASS", "output": str(out)[:40]}
            print(f"  [{lang}] PASS — output: {str(out)[:40]!r}")
        except Exception as exc:
            results[lang] = {"status": "FAIL", "error": str(exc)}
            print(f"  [{lang}] FAIL — {exc}")

    failed = [l for l, r in results.items() if r["status"] != "PASS"]
    if failed:
        print(f"\nFailed: {failed}")
        return 1

    print("\nAll languages OK.")
    print("\nStart both servers with:")
    print("  .venv/bin/python services/tts/server.py   # TTS  on :8765")
    print("  .venv/bin/python services/asr/server.py   # ASR  on :8766")
    return 0


if __name__ == "__main__":
    sys.exit(main())
