// ASR server availability check — mirrors the pattern in speech.js for Parler TTS.

export const ASR_URL = "http://localhost:8766";

let _asrAvailable = null;

export async function checkASRAvailable() {
  if (_asrAvailable !== null) return _asrAvailable;
  try {
    const res = await fetch(`${ASR_URL}/health`, { signal: AbortSignal.timeout(1200) });
    _asrAvailable = res.ok;
  } catch {
    _asrAvailable = false;
  }
  return _asrAvailable;
}

export const isASRAvailable = () => _asrAvailable === true;

// Kick off check immediately on import so it's cached before user taps mic.
if (typeof window !== "undefined") {
  checkASRAvailable().catch(() => {});
}
