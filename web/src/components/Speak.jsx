import { useState, useEffect } from "react";
import { speak, preloadSpeech, canSpeak, pauseSpeech, resumeSpeech, stopSpeech, isParlerAvailable, checkParlerAvailable } from "../lib/speech.js";
import { Speaker, Pause, Play } from "./Marks.jsx";
import { t } from "../i18n/strings.js";

export default function Speak({ text, lang = "kn", variant = "pill", onPhoto = false }) {
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
    setIsPaused(false);
    setIsPlaying(true);
    await speak(text, lang);
    setIsPlaying(false);
  };

  const handleToggle = () => {
    if (isPaused) {
      resumeSpeech();
      setIsPaused(false);
    } else {
      pauseSpeech();
      setIsPaused(true);
    }
  };

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
