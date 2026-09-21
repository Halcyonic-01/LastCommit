// Audio advisory playback.
//
// Strategy (in priority order):
//   1. Local Indic Parler-TTS server (http://localhost:8765) — high-quality,
//      runs offline after the one-time model download, supports kn/hi/te/en.
//   2. Browser SpeechSynthesis — universal fallback, quality varies by device.
//
// The Speak component calls speak() and gets the best available option
// automatically; it never has to know which path ran.

const TTS_URL = "http://localhost:8765";
const SPEECH_LANG = { kn: "kn-IN", hi: "hi-IN", te: "te-IN", en: "en-IN" };

// Cached availability — checked once per page load.
let _parlerAvailable = null;

/** Returns true if the local Parler server responded to /health. */
export async function checkParlerAvailable() {
  if (_parlerAvailable !== null) return _parlerAvailable;
  try {
    const res = await fetch(`${TTS_URL}/health`, { signal: AbortSignal.timeout(1200) });
    _parlerAvailable = res.ok;
  } catch {
    _parlerAvailable = false;
  }
  return _parlerAvailable;
}

/** Synchronous read of the cached result — false until checkParlerAvailable() resolves. */
export const isParlerAvailable = () => _parlerAvailable === true;

// Kick off the health check immediately so it's ready by the time the user taps Listen.
if (typeof window !== "undefined") {
  checkParlerAvailable().catch(() => {});
}

// Currently playing AudioBufferSourceNode so we can pause/stop it.
let _currentSource = null;
let _audioCtx = null;

function _getAudioCtx() {
  if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return _audioCtx;
}

/** Play WAV bytes via Web Audio API. Returns the source node for pause/stop. */
async function _playWav(bytes) {
  const ctx = _getAudioCtx();
  if (ctx.state === "suspended") await ctx.resume();
  const buffer = await ctx.decodeAudioData(bytes.slice(0)); // slice = copy, avoids detach
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  source.start(0);
  _currentSource = source;
  return source;
}

/**
 * Speak text in the given language.
 * Tries the local Parler server first; falls back to SpeechSynthesis.
 * Returns "parler", "browser", or false if nothing could play.
 */
export async function speak(text, lang = "kn") {
  if (!text) return false;
  stopSpeech();

  // --- Try Parler TTS ---
  if (await checkParlerAvailable()) {
    try {
      const res = await fetch(`${TTS_URL}/synthesize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, lang }),
        signal: AbortSignal.timeout(30000), // TTS can take a few seconds
      });
      if (res.ok) {
        const bytes = await res.arrayBuffer();
        await _playWav(bytes);
        return "parler";
      }
    } catch {
      // Server went away mid-session — fall through to browser TTS
      _parlerAvailable = false;
    }
  }

  // --- Browser SpeechSynthesis fallback ---
  return _browserSpeak(text, lang);
}

function _browserSpeak(text, lang) {
  if (!("speechSynthesis" in window)) return false;
  const tag = SPEECH_LANG[lang] || "kn-IN";
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = tag;
  u.rate = 0.88;
  const v = window.speechSynthesis.getVoices().find((x) => x.lang?.startsWith(tag.slice(0, 2)));
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
  return "browser";
}

export const canSpeak = () =>
  typeof window !== "undefined" &&
  ("speechSynthesis" in window || typeof AudioContext !== "undefined" || typeof window.webkitAudioContext !== "undefined");

export function stopSpeech() {
  // Stop Parler audio
  if (_currentSource) {
    try { _currentSource.stop(); } catch { /* already stopped */ }
    _currentSource = null;
  }
  // Stop browser TTS
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

export function pauseSpeech() {
  if (_currentSource && _audioCtx) {
    _audioCtx.suspend().catch(() => {});
  }
  if ("speechSynthesis" in window) window.speechSynthesis.pause();
}

export function resumeSpeech() {
  if (_audioCtx && _audioCtx.state === "suspended") {
    _audioCtx.resume().catch(() => {});
  }
  if ("speechSynthesis" in window) window.speechSynthesis.resume();
}

