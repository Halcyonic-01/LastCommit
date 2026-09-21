import { useState, useEffect, useRef } from "react";
import { speak, speakSequence, splitSentences, preloadSpeech, canSpeak, pauseSpeech, resumeSpeech, stopSpeech, isParlerAvailable, checkParlerAvailable, unlockAudio, prerenderedFile } from "../lib/speech.js";
import { Speaker, Pause, Play } from "./Marks.jsx";
import { t } from "../i18n/strings.js";

export default function Speak({ text, lang = "kn", variant = "pill", onPhoto = false }) {
  // A real <audio> element, in the DOM, pointed at a file we shipped. Playing it is the
  // first statement of the click handler with nothing awaited before it, which is the
  // only arrangement no autoplay policy can refuse. Everything else is the fallback.
  const clip = prerenderedFile(text, lang);
  const clipRef = useRef(null);
  const [isPaused, setIsPaused] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [hd, setHd] = useState(isParlerAvailable());

  // Re-check once the async health probe resolves on page load.
  useEffect(() => {
    checkParlerAvailable().then((ok) => setHd(ok)).catch(() => {});
    // Generate the selected language in the background so tapping Listen does
    // not have to wait for the neural synthesizer on the critical path.
    const timer = setTimeout(() => preloadSpeech(text, lang), 80);
    // A language switch must stop any audio generated for the previous text.
    return () => {
      clearTimeout(timer);
      stopSpeech();
    };
  }, [text, lang]);

  if (!canSpeak() || !text) return null;
  const cls = onPhoto ? " -onphoto" : "";
  const label = `${t("listen", lang)} — listen`;

  const handleSpeak = async () => {
    const el = clipRef.current;
    if (el) {
      try { el.currentTime = 0; } catch { /* not seekable yet */ }
      el.play().catch(() => {});      // synchronous: still inside the click
      setIsPaused(false);
      return;
    }
    // Synthesis can take several seconds, and by the time the audio arrives this click
    // no longer counts as a user gesture — so open the audio device now, not then.
    unlockAudio();
    setIsPaused(false);
    setIsPlaying(true);
    // One sentence at a time: the first plays while the rest are still being made,
    // instead of the farmer waiting for the whole paragraph before hearing anything.
    await speakSequence(splitSentences(text), lang);
    setIsPlaying(false);
  };

  const handleToggle = () => {
    const el = clipRef.current;
    if (isPaused) {
      if (el) el.play().catch(() => {}); else resumeSpeech();
      setIsPaused(false);
    } else {
      if (el) el.pause(); else pauseSpeech();
      setIsPaused(true);
    }
  };

  const Clip = clip ? <audio ref={clipRef} src={clip} preload="auto" /> : null;

  const Icon = isPaused ? Play : Pause;
  const toggleLabel = isPaused ? "Resume" : "Pause";

  const HdBadge = hd ? (
    <span
      title="High-quality Indic Parler-TTS"
      style={{
        fontSize: 9, fontWeight: 800, letterSpacing: ".06em",
        background: "var(--green, #2d9e5f)", color: "#fff",
        borderRadius: 3, padding: "1px 4px", lineHeight: 1.4,
        verticalAlign: "middle", marginLeft: 3,
      }}
    >HD</span>
  ) : null;

  if (variant === "icon") {
    return (
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {Clip}
        <button type="button" className={`speak-ico${cls}`} onClick={handleSpeak}
          aria-label={label} disabled={isPlaying}>
          <Speaker size={22} />{HdBadge}
        </button>
        <button type="button" className={`speak-ico${cls}`} onClick={handleToggle} aria-label={toggleLabel}>
          <Icon size={22} />
        </button>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      {Clip}
      <button type="button" className={`speak${cls}`} onClick={handleSpeak}
        aria-label={label} disabled={isPlaying}>
        <Speaker size={20} /> {t("listen", lang)}{HdBadge}
      </button>
      <button type="button" className={`speak-ico${cls}`} onClick={handleToggle} aria-label={toggleLabel}>
        <Icon size={22} />
      </button>
    </div>
  );
}
