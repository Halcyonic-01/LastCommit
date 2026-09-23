import { useState, useRef, useEffect } from "react";
import { unlockAudio } from "../lib/speech.js";
import { t } from "../i18n/strings.js";
import {
  isASRAvailable, checkASRAvailable, ASR_URL,
  normalizeSpeechLang,
} from "../lib/asr.js";

const STALL_MS = 25000;

/**
 * Farmer Voice Assistant for VarshaDrishti.
 *
 * Pipeline:
 *   Farmer microphone
 *   → Server Speech-to-Text (Sarvam Saaras primary / IndicConformer fallback)
 *   → VarshaDrishti Grounded Assistant Logic
 *   → Server Text-to-Speech (Sarvam Bulbul primary / Parler fallback)
 *   → Audio response played to farmer
 */
export default function VoiceAssistant({
  lang = "kn",
  areaId = "KGIS-H-180901",
  pageDescription = "",
}) {
  lang = normalizeSpeechLang(lang);
  const [serverOnline, setServerOnline] = useState(isASRAvailable() ? true : null);
  const [state, setState] = useState("idle"); // idle | listening | processing | understanding | generating | speaking | done
  const [transcript, setTranscript] = useState("");
  const [reply, setReply] = useState("");
  const [error, setError] = useState("");

  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const stallRef = useRef(null);
  const activeAudioRef = useRef(null);
  const pressStartRef = useRef(0);

  useEffect(() => {
    checkASRAvailable()
      .then(setServerOnline)
      .catch(() => setServerOnline(false));
  }, []);

  const clearStall = () => {
    if (stallRef.current) {
      clearTimeout(stallRef.current);
      stallRef.current = null;
    }
  };

  useEffect(() => clearStall, []);

  const fail = (message) => {
    clearStall();
    stopCurrentAudio();
    setError(message || t("voiceError", lang));
    setState("idle");
  };

  const armStall = (message) => {
    clearStall();
    stallRef.current = setTimeout(() => fail(message), STALL_MS);
  };

  const stopCurrentAudio = () => {
    if (activeAudioRef.current) {
      try {
        activeAudioRef.current.pause();
        activeAudioRef.current.currentTime = 0;
      } catch {
        /* audio cleanup */
      }
      activeAudioRef.current = null;
    }
  };

  const playAudioBase64 = (base64Data, mimeType = "audio/wav") => {
    try {
      stopCurrentAudio();
      const binaryString = atob(base64Data);
      const len = binaryString.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      const blob = new Blob([bytes], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      activeAudioRef.current = audio;

      setState("speaking");
      audio.onended = () => {
        URL.revokeObjectURL(url);
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
          setState("done");
        }
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
          setState("done");
        }
      };

      const playPromise = audio.play();
      if (playPromise !== undefined) {
        playPromise.catch((err) => {
          console.warn("Audio autoplay blocked or failed:", err);
          setState("done");
        });
      }
    } catch (err) {
      console.error("Failed to decode and play audio:", err);
      setState("done");
    }
  };

  const startRecording = async () => {
    unlockAudio();
    stopCurrentAudio();
    setError("");
    setTranscript("");
    setReply("");
    pressStartRef.current = Date.now();

    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        throw new Error("Microphone recording not supported on this device.");
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];

      const mimeTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/ogg;codecs=opus",
        "audio/mp4",
      ];
      const mimeType = mimeTypes.find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorderRef.current = recorder;
      recorder.start(100);
      setState("listening");
    } catch (err) {
      fail(err?.name === "NotAllowedError"
        ? "Microphone access was denied. Please allow microphone permissions."
        : "Could not open microphone. Please try again.");
    }
  };

  const stopRecording = async () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      if (state === "listening") setState("idle");
      return;
    }

    setState("processing");
    armStall("Processing took too long. Please try again.");

    await new Promise((resolve) => {
      recorder.onstop = resolve;
      recorder.stop();
      recorder.stream.getTracks().forEach((track) => track.stop());
    });

    const mimeType = recorder.mimeType || "audio/webm";
    const blob = new Blob(chunksRef.current, { type: mimeType });

    if (blob.size < 400) {
      fail("Recording was too short. Please speak clearly.");
      return;
    }

    setState("understanding");

    try {
      const ext = mimeType.includes("ogg") ? "ogg" : mimeType.includes("mp4") ? "mp4" : "webm";
      const form = new FormData();
      form.append("audio", blob, `farmer_voice.${ext}`);
      form.append("lang", lang);
      form.append("area_id", areaId || "KGIS-H-180901");

      const res = await fetch(`${ASR_URL}/transcribe`, {
        method: "POST",
        headers: {
          "X-Lang": lang,
          "X-Area-Id": areaId || "KGIS-H-180901",
        },
        body: form,
        signal: AbortSignal.timeout(30000),
      });

      if (!res.ok) {
        let errJson = null;
        try { errJson = await res.json(); } catch { /* ignore */ }
        throw new Error(errJson?.error || `Server returned error (${res.status})`);
      }

      const data = await res.json();
      clearStall();

      const recognized = (data.transcript || "").trim();
      const answer = (data.reply_text || "").trim();

      if (!recognized && !answer) {
        fail("I could not hear a clear question. Please try again.");
        return;
      }

      setTranscript(recognized);
      setReply(answer);

      // Play synthesized audio if provided
      if (data.audio_base64) {
        setState("generating");
        playAudioBase64(data.audio_base64, data.audio_format || "audio/wav");
      } else {
        // Even if TTS failed or not configured, show text answer and mark done
        setState("done");
      }
    } catch (err) {
      fail(err.message || "Could not reach the voice service. Please try again.");
    }
  };

  const handlePointerDown = (e) => {
    // Only primary mouse click or touch
    if (e.button !== undefined && e.button !== 0) return;
    if (state === "idle" || state === "done") {
      startRecording();
    }
  };

  const handlePointerUp = () => {
    if (state === "listening") {
      stopRecording();
    }
  };

  const reset = () => {
    clearStall();
    stopCurrentAudio();
    setTranscript("");
    setReply("");
    setError("");
    setState("idle");
  };

  // State checks
  const isListening = state === "listening";
  const isProcessing = state === "processing";
  const isUnderstanding = state === "understanding";
  const isGenerating = state === "generating";
  const isSpeaking = state === "speaking";
  const isBusy = isProcessing || isUnderstanding || isGenerating;
  const isDone = state === "done";

  // If server is explicitly offline and not probed yet, we still render so the user sees the assistant
  return (
    <div style={{ marginTop: 20, borderTop: "1px solid var(--rule2)", paddingTop: 16 }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: ".08em",
              color: "var(--ink3)",
              textTransform: "uppercase",
            }}
          >
            🎙 {t("voiceAssistant", lang)}
          </span>
          <span
            style={{
              fontSize: 9,
              fontWeight: 800,
              background: "#10b981",
              color: "#fff",
              borderRadius: 3,
              padding: "1px 5px",
              letterSpacing: ".05em",
            }}
          >
            SARVAM AI
          </span>
        </div>
      </div>

      {/* Main voice interaction area */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
        <button
          type="button"
          onPointerDown={handlePointerDown}
          onPointerUp={handlePointerUp}
          onPointerCancel={isListening ? handlePointerUp : undefined}
          disabled={isBusy}
          aria-label={isListening ? t("listening", lang) : t("holdToSpeak", lang)}
          style={{
            width: 76,
            height: 76,
            borderRadius: "50%",
            border: "none",
            cursor: isBusy ? "not-allowed" : "pointer",
            background: isListening
              ? "#e11d48"
              : isSpeaking
              ? "#10b981"
              : isBusy
              ? "var(--paper3)"
              : "var(--water2)",
            color: "#fff",
            fontSize: 32,
            boxShadow: isListening
              ? "0 0 0 8px rgba(225, 29, 72, 0.25), 0 0 0 16px rgba(225, 29, 72, 0.10)"
              : isSpeaking
              ? "0 0 0 8px rgba(16, 185, 129, 0.25), 0 0 0 16px rgba(16, 185, 129, 0.10)"
              : "none",
            transition: "box-shadow 0.2s, background 0.2s, transform 0.1s",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            userSelect: "none",
            WebkitUserSelect: "none",
            touchAction: "none",
          }}
        >
          {isBusy ? "⏳" : isSpeaking ? "🔊" : "🎙"}
        </button>

        {/* State label text */}
        <div style={{ fontSize: 13, color: "var(--ink2)", minHeight: 20, textAlign: "center", fontWeight: 500 }}>
          {isListening && <span style={{ color: "#e11d48", fontWeight: 700 }}>{t("listening", lang)}</span>}
          {isProcessing && <span>{t("processing", lang)}</span>}
          {isUnderstanding && <span>{t("understanding", lang)}</span>}
          {isGenerating && <span>{t("generating", lang)}</span>}
          {isSpeaking && <span style={{ color: "#10b981", fontWeight: 700 }}>{t("speaking", lang)}</span>}
          {!isListening && !isBusy && !isSpeaking && !isDone && !error && (
            <span>{t("holdToSpeak", lang)}</span>
          )}
        </div>

        {/* Cancel button if busy */}
        {isBusy && (
          <button
            type="button"
            onClick={reset}
            style={{
              fontSize: 11,
              background: "none",
              border: "none",
              color: "var(--ink3)",
              cursor: "pointer",
              padding: 0,
              textDecoration: "underline",
            }}
          >
            {t("tryAgain", lang)}
          </button>
        )}

        {/* Error notice */}
        {error && (
          <div
            style={{
              fontSize: 12,
              color: "var(--risk)",
              textAlign: "center",
              background: "rgba(220, 50, 50, 0.08)",
              padding: "6px 12px",
              borderRadius: 6,
              maxWidth: "100%",
            }}
          >
            {error}
          </div>
        )}

        {/* Result bubble */}
        {(isDone || isSpeaking) && (transcript || reply) && (
          <div
            style={{
              width: "100%",
              background: "var(--paper3)",
              borderRadius: 8,
              padding: "12px 14px",
              fontSize: 13.5,
              marginTop: 4,
              border: "1px solid var(--rule2)",
            }}
          >
            {transcript && (
              <div style={{ marginBottom: 8, paddingBottom: 8, borderBottom: "1px dashed var(--rule2)" }}>
                <span
                  style={{
                    fontSize: 10.5,
                    color: "var(--ink3)",
                    fontWeight: 700,
                    letterSpacing: ".06em",
                    textTransform: "uppercase",
                  }}
                >
                  {t("youSaid", lang)}:{" "}
                </span>
                <span className="kn" style={{ color: "var(--ink)", fontWeight: 600 }}>
                  {transcript}
                </span>
              </div>
            )}
            {reply && (
              <div
                className="kn"
                style={{
                  color: "var(--water2)",
                  fontWeight: 600,
                  fontSize: 14.5,
                  lineHeight: 1.4,
                }}
              >
                {reply}
              </div>
            )}
            {isDone && (
              <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end" }}>
                <button
                  type="button"
                  onClick={reset}
                  style={{
                    fontSize: 11.5,
                    background: "none",
                    border: "none",
                    color: "var(--ink3)",
                    cursor: "pointer",
                    padding: 0,
                    textDecoration: "underline",
                  }}
                >
                  {t("tryAgain", lang)}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
