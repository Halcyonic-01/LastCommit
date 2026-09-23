import { useState, useEffect, useRef } from "react";
import {
  speak,
  preloadSpeech,
  canSpeak,
  stopSpeech,
  unlockAudio,
  prerenderedFile,
  waitForSpeechEnd,
} from "../lib/speech.js";
import { Speaker, Stop } from "./Marks.jsx";
import { t } from "../i18n/strings.js";

export default function Speak({ text, lang = "kn", variant = "pill", onPhoto = false }) {
  const clip = prerenderedFile(text, lang);
  const clipRef = useRef(null);
  const [status, setStatus] = useState("idle"); // "idle" | "preparing" | "playing"

  useEffect(() => {
    // Background preload into memory & browser cache
    const timer = setTimeout(() => preloadSpeech(text, lang), 100);
    return () => {
      clearTimeout(timer);
      stopSpeech();
      setStatus("idle");
    };
  }, [text, lang]);

  if (!canSpeak() || !text) return null;
  const cls = onPhoto ? " -onphoto" : "";

  const handleStop = () => {
    const el = clipRef.current;
    if (el) {
      try {
        el.pause();
        el.currentTime = 0;
      } catch {}
    }
    stopSpeech();
    setStatus("idle");
  };

  const handleSpeak = async () => {
    if (status === "playing") {
      handleStop();
      return;
    }

    if (status === "preparing") {
      handleStop();
      return;
    }

    const el = clipRef.current;
    if (el) {
      try {
        el.currentTime = 0;
        el.play().then(() => {
          setStatus("playing");
        }).catch(() => {});
        return;
      } catch {
        // Fall back to server synthesis if pre-rendered playback fails
      }
    }

    unlockAudio();
    setStatus("preparing");

    try {
      const ok = await speak(text, lang);
      if (ok) {
        setStatus("playing");
        await waitForSpeechEnd();
        setStatus("idle");
      } else {
        setStatus("idle");
      }
    } catch {
      setStatus("idle");
    }
  };

  const Clip = clip ? (
    <audio
      ref={clipRef}
      src={clip}
      preload="auto"
      onEnded={() => setStatus("idle")}
    />
  ) : null;

  const isPreparing = status === "preparing";
  const isPlaying = status === "playing";

  const getLabel = () => {
    if (isPlaying) return t("stop", lang);
    if (isPreparing) return t("preparing", lang);
    return t("listen", lang);
  };

  const renderIcon = () => {
    if (isPlaying) return <Stop size={variant === "icon" ? 20 : 18} />;
    if (isPreparing) {
      return (
        <span
          style={{
            display: "inline-block",
            width: 14,
            height: 14,
            borderRadius: "50%",
            border: "2px solid currentColor",
            borderRightColor: "transparent",
            animation: "spin 0.8s linear infinite",
          }}
        />
      );
    }
    return <Speaker size={variant === "icon" ? 22 : 20} />;
  };

  if (variant === "icon") {
    return (
      <div style={{ display: "inline-flex", alignItems: "center" }}>
        {Clip}
        <button
          type="button"
          className={`speak-ico${cls}${isPlaying ? " -active" : ""}`}
          onClick={handleSpeak}
          aria-label={getLabel()}
          title={getLabel()}
        >
          {renderIcon()}
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: "inline-flex", alignItems: "center" }}>
      {Clip}
      <button
        type="button"
        className={`speak${cls}${isPlaying ? " -active" : ""}`}
        onClick={handleSpeak}
        aria-label={getLabel()}
        style={{
          cursor: "pointer",
          transition: "all 0.2s ease",
          background: isPlaying ? "var(--ink)" : "transparent",
          color: isPlaying ? "var(--paper2)" : "inherit",
          borderColor: isPlaying ? "var(--ink)" : undefined,
        }}
      >
        {renderIcon()}
        <span>{getLabel()}</span>
      </button>
    </div>
  );
}
