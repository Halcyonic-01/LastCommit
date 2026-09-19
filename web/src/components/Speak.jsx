import { useState } from "react";
import { speak, canSpeak, stopSpeech, pauseSpeech, resumeSpeech } from "../lib/speech.js";
import { Speaker, Pause, Play } from "./Marks.jsx";
import { t } from "../i18n/strings.js";

export default function Speak({ text, lang = "kn", variant = "pill", onPhoto = false }) {
  const [isPaused, setIsPaused] = useState(false);

  if (!canSpeak() || !text) return null;
  const cls = onPhoto ? " -onphoto" : "";
  const label = `${t("listen", lang)} — listen`;

  const handleSpeak = () => {
    setIsPaused(false);
    speak(text, lang);
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

  if (variant === "icon") {
    return (
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button type="button" className={`speak-ico${cls}`} onClick={handleSpeak} aria-label={label}>
          <Speaker size={22} />
        </button>
        <button type="button" className={`speak-ico${cls}`} onClick={handleToggle} aria-label={toggleLabel}>
          <Icon size={22} />
        </button>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <button type="button" className={`speak${cls}`} onClick={handleSpeak} aria-label={label}>
        <Speaker size={20} /> {t("listen", lang)}
      </button>
      <button type="button" className={`speak-ico${cls}`} onClick={handleToggle} aria-label={toggleLabel}>
        <Icon size={22} />
      </button>
    </div>
  );
}
