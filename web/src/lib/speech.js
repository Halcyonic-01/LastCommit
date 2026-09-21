// Language-safe text-to-speech for the farmer pages.
// Local Indic Parler-TTS is primary; browser speech is a strict same-language fallback.

const TTS_URL = import.meta.env.VITE_TTS_SERVER_URL || "http://localhost:8765";
const SPEECH_LANG = { kn: "kn-IN", hi: "hi-IN", te: "te-IN", en: "en-IN" };
const SUPPORTED_LANGS = new Set(Object.keys(SPEECH_LANG));

let _parlerAvailable = null;
let _healthRequest = null;
let _currentSource = null;
let _audioCtx = null;
let _speechGeneration = 0;
const _audioCache = new Map();
const _audioRequests = new Map();

function normalizeLang(lang) {
  const code = String(lang || "kn").toLowerCase().split("-")[0];
  return SUPPORTED_LANGS.has(code) ? code : "kn";
}

function _audioKey(text, lang) { return `tts-v3\u0000${lang}\u0000${text}`; }

// Pre-rendered clips shipped in web/public. Indic Parler-TTS takes several seconds on
// a sentence this long, which is too slow to demonstrate live, so the sentences we know
// in advance are rendered once and served as files.
//
// The key is the EXACT sentence the clip speaks. That is the whole safety property: if
// the forecast changes and the advisory text changes with it, the key stops matching and
// synthesis takes over. A stale clip can never speak advice the screen is not showing.
const PRERENDERED = [
  { lang: "kn", file: "/demo_crida.wav",
    text: "ಮಣ್ಣಿನ ತೇವ ಉಳಿಸಿ, ಈ ವಾರ ಮಳೆಯ ಅಗತ್ಯವಿರುವ ಕೆಲಸ ಮುಂದೂಡಿ" },
];

// Trailing punctuation differs between the rules engine and the ASR server's reply
// ("...ಮುಂದೂಡಿ" vs "...ಮುಂದೂಡಿ."); nothing else is allowed to differ.
const _norm = (t) => String(t || "").replace(/\s+/g, " ").trim().replace(/[.।]+$/, "");

function _prerendered(text, lang) {
  const want = _norm(text);
  return PRERENDERED.find((c) => c.lang === lang && _norm(c.text) === want) || null;
}

async function _fetchPrerendered(clip) {
  const key = _audioKey(clip.text, clip.lang);
  if (_audioCache.has(key)) return _audioCache.get(key);
  const res = await fetch(clip.file);
  if (!res.ok) throw new Error(`${clip.file} -> ${res.status}`);
  const bytes = await res.arrayBuffer();
  _audioCache.set(key, bytes);
  return bytes;
}

// A failed probe is not permanent: the user may start the TTS server after opening the PWA.
export async function checkParlerAvailable(force = false) {
  if (!force && _parlerAvailable !== null) return _parlerAvailable;
  if (_healthRequest && !force) return _healthRequest;
  _healthRequest = fetch(`${TTS_URL}/health`, { signal: AbortSignal.timeout(1500) })
    .then((res) => { _parlerAvailable = res.ok; return _parlerAvailable; })
    .catch(() => { _parlerAvailable = false; return false; })
    .finally(() => { _healthRequest = null; });
  return _healthRequest;
}

export const isParlerAvailable = () => _parlerAvailable === true;
if (typeof window !== "undefined") checkParlerAvailable().catch(() => {});

async function _fetchParlerAudio(text, lang) {
  lang = normalizeLang(lang);
  const key = _audioKey(text, lang);
  if (_audioCache.has(key)) return _audioCache.get(key);
  if (_audioRequests.has(key)) return _audioRequests.get(key);
  const request = (async () => {
    // Retry after an earlier failure so starting the local service after the
    // page opened still works without a reload.
    if (!(await checkParlerAvailable(_parlerAvailable === false))) return null;
    try {
      const res = await fetch(`${TTS_URL}/synthesize`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "audio/wav" },
        body: JSON.stringify({ text, lang }),
        signal: AbortSignal.timeout(45000),
      });
      if (!res.ok || !(res.headers.get("content-type") || "").includes("audio")) return null;
      const bytes = await res.arrayBuffer();
      _audioCache.set(key, bytes);
      while (_audioCache.size > 8) _audioCache.delete(_audioCache.keys().next().value);
      return bytes;
    } catch {
      _parlerAvailable = false;
      return null;
    } finally { _audioRequests.delete(key); }
  })();
  _audioRequests.set(key, request);
  return request;
}

export function preloadSpeech(text, lang = "kn") {
  if (text) _fetchParlerAudio(text, normalizeLang(lang)).catch(() => {});
}

function _getAudioCtx() {
  if (!_audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    _audioCtx = new Ctx();
  }
  return _audioCtx;
}

async function _playWav(bytes, generation) {
  const ctx = _getAudioCtx();
  if (!ctx) return false;
  if (ctx.state === "suspended") await ctx.resume();
  const buffer = await ctx.decodeAudioData(bytes.slice(0));
  if (generation !== _speechGeneration) return false;
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  source.onended = () => { if (_currentSource === source) _currentSource = null; };
  source.start(0);
  _currentSource = source;
  return true;
}

function _browserVoice(lang, voices) {
  const wanted = SPEECH_LANG[lang].toLowerCase();
  // Do not select an unrelated installed voice. That is worse than reporting that
  // browser fallback is unavailable because it makes the language switch deceptive.
  return voices.find((v) => v.lang?.toLowerCase() === wanted)
    || voices.find((v) => v.lang?.toLowerCase().startsWith(`${lang}-`))
    || null;
}

async function _browserSpeak(text, lang) {
  if (!("speechSynthesis" in window)) return false;
  let voices = window.speechSynthesis.getVoices();
  if (!voices.length) {
    voices = await new Promise((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        window.speechSynthesis.removeEventListener("voiceschanged", finish);
        resolve(window.speechSynthesis.getVoices());
      };
      window.speechSynthesis.addEventListener("voiceschanged", finish, { once: true });
      setTimeout(finish, 800);
    });
  }
  const voice = _browserVoice(lang, voices);
  if (!voice) return false;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = voice.lang || SPEECH_LANG[lang];
  utterance.voice = voice;
  utterance.rate = 0.88;
  window.speechSynthesis.speak(utterance);
  return true;
}

export async function speak(text, lang = "kn") {
  if (!text || typeof window === "undefined") return false;
  lang = normalizeLang(lang);
  stopSpeech();
  const generation = _speechGeneration;

  // A clip we rendered earlier for this exact sentence plays instantly. It goes through
  // _playWav like everything else, so stopSpeech/pause/resume still control it — an
  // `new Audio()` here would keep playing over the top of whatever came next.
  const clip = _prerendered(text, lang);
  if (clip) {
    try {
      const pre = await _fetchPrerendered(clip);
      if (generation === _speechGeneration && await _playWav(pre, generation)) return "prerendered";
    } catch {
      // the file is missing or undecodable — synthesise it instead of going silent
    }
    if (generation !== _speechGeneration) return false;
  }

  // Always try the requested-language local voice first. This fixes the common
  // failure where Chrome's installed English voice preempts Indic Parler-TTS.
  const bytes = await _fetchParlerAudio(text, lang);
  if (bytes && generation === _speechGeneration) {
    try { if (await _playWav(bytes, generation)) return "parler"; } catch { /* fallback below */ }
  }
  if (generation !== _speechGeneration) return false;
  return (await _browserSpeak(text, lang)) ? "browser" : false;
}

export const canSpeak = () => typeof window !== "undefined" && (
  "speechSynthesis" in window || Boolean(window.AudioContext || window.webkitAudioContext)
);

export function stopSpeech() {
  _speechGeneration += 1;
  if (_currentSource) {
    try { _currentSource.stop(); } catch { /* already ended */ }
    _currentSource = null;
  }
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
}

export function pauseSpeech() {
  if (_currentSource && _audioCtx) _audioCtx.suspend().catch(() => {});
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.pause();
}

export function resumeSpeech() {
  if (_audioCtx?.state === "suspended") _audioCtx.resume().catch(() => {});
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.resume();
}
