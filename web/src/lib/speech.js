// On-device speech. Free, works offline on most Android builds, no API key.
// Voice is on every unit a farmer has to act on — the one finding every
// low-literacy study agrees on.
const SPEECH = { kn: "kn-IN", hi: "hi-IN", te: "te-IN", en: "en-IN" };

export function speak(text, lang = "kn") {
  if (!text || !("speechSynthesis" in window)) return false;
  const tag = SPEECH[lang] || "kn-IN";
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = tag;
  u.rate = 0.88; // slower than a notification — this is a decision being read out
  const v = window.speechSynthesis.getVoices().find((x) => x.lang?.startsWith(tag.slice(0, 2)));
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
  return true;
}

export const canSpeak = () => typeof window !== "undefined" && "speechSynthesis" in window;

export function stopSpeech() {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}

export function pauseSpeech() {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.pause();
  }
}

export function resumeSpeech() {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.resume();
  }
}
