import { speak, canSpeak } from "../lib/speech.js";
import { Speaker } from "./Marks.jsx";
import { t } from "../i18n/strings.js";

export default function Speak({ text, lang = "kn", variant = "pill", onPhoto = false }) {
  if (!canSpeak() || !text) return null;
  const cls = onPhoto ? " -onphoto" : "";
  const label = `${t("listen", lang)} — listen`;
  if (variant === "icon") {
    return (
      <button type="button" className={`speak-ico${cls}`} onClick={() => speak(text, lang)} aria-label={label}>
        <Speaker size={22} />
      </button>
    );
  }
  return (
    <button type="button" className={`speak${cls}`} onClick={() => speak(text, lang)} aria-label={label}>
      <Speaker size={20} /> {t("listen", lang)}
    </button>
  );
}
