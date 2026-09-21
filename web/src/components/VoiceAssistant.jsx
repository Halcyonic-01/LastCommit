import { useState, useRef, useEffect } from "react";
import { speak, checkParlerAvailable } from "../lib/speech.js";
import { t } from "../i18n/strings.js";
import { isASRAvailable, checkASRAvailable, ASR_URL } from "../lib/asr.js";

/**
 * Hold-to-speak voice assistant for the farmer.
 *
 * Renders only when the ASR server is reachable (:8766/health).
 * On hold: records via MediaRecorder → on release: POSTs to /transcribe
 * → shows transcript → speaks reply via Parler TTS.
 */
export default function VoiceAssistant({ lang = "kn", areaId }) {
  const [asr, setAsr] = useState(isASRAvailable());
  const [state, setState] = useState("idle"); // idle | listening | processing | done
  const [transcript, setTranscript] = useState("");
  const [reply, setReply] = useState("");
  const [error, setError] = useState("");

  const recorderRef = useRef(null);
  const chunksRef = useRef([]);

  useEffect(() => {
    checkASRAvailable().then(setAsr).catch(() => setAsr(false));
  }, []);

  if (!asr) return null;

  const startRecording = async () => {
    setError("");
    setTranscript("");
    setReply("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorderRef.current = recorder;
      recorder.start(100); // collect every 100ms
      setState("listening");
    } catch (err) {
      setError("Microphone access denied.");
      setState("idle");
    }
  };

  const stopRecording = async () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    setState("processing");

    await new Promise((resolve) => {
      recorder.onstop = resolve;
      recorder.stop();
      recorder.stream.getTracks().forEach((t) => t.stop());
    });

    const blob = new Blob(chunksRef.current, { type: "audio/webm" });
    if (blob.size < 500) {
      setError("Audio too short. Hold the button and speak.");
      setState("idle");
      return;
    }

    try {
      const form = new FormData();
      form.append("audio", blob, "recording.webm");
      const res = await fetch(`${ASR_URL}/transcribe`, {
        method: "POST",
        headers: { "X-Lang": lang },
        body: form,
        signal: AbortSignal.timeout(30000),
      });
      if (!res.ok) throw new Error(`ASR error ${res.status}`);
      const data = await res.json();
      setTranscript(data.transcript || "");
      setReply(data.reply_text || "");
      setState("done");
      // Speak the reply through Parler TTS
      if (data.reply_text) {
        await checkParlerAvailable();
        speak(data.reply_text, lang);
      }
    } catch (err) {
      setError("Could not reach the ASR server.");
      setState("idle");
    }
  };

  const reset = () => {
    setTranscript("");
    setReply("");
    setError("");
    setState("idle");
  };

  const isListening = state === "listening";
  const isProcessing = state === "processing";
  const isDone = state === "done";

  return (
    <div style={{ marginTop: 20, borderTop: "1px solid var(--rule2)", paddingTop: 16 }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".08em",
          color: "var(--ink3)", textTransform: "uppercase" }}>
          🎙 {t("voiceAssistant", lang)}
        </span>
        <span style={{ fontSize: 9, fontWeight: 800, background: "#6c47ff", color: "#fff",
          borderRadius: 3, padding: "1px 5px", letterSpacing: ".05em" }}>AI</span>
      </div>

      {/* Mic button */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
        <button
          type="button"
          onPointerDown={startRecording}
          onPointerUp={stopRecording}
          onPointerLeave={isListening ? stopRecording : undefined}
          disabled={isProcessing}
          aria-label={isListening ? t("listening", lang) : t("holdToSpeak", lang)}
          style={{
            width: 72, height: 72, borderRadius: "50%",
            border: "none", cursor: isProcessing ? "not-allowed" : "pointer",
            background: isListening ? "#e33" : isProcessing ? "var(--paper3)" : "var(--water2)",
            color: "#fff", fontSize: 30,
            boxShadow: isListening ? "0 0 0 8px rgba(220,50,50,.25), 0 0 0 16px rgba(220,50,50,.10)" : "none",
            transition: "box-shadow .2s, background .2s",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
        >
          {isProcessing ? "⏳" : "🎙"}
        </button>

        {/* Status text */}
        <div style={{ fontSize: 12, color: "var(--ink3)", minHeight: 18, textAlign: "center" }}>
          {isListening && <span style={{ color: "#e33" }}>{t("listening", lang)}</span>}
          {isProcessing && <span>{t("processing", lang)}</span>}
          {!isListening && !isProcessing && !isDone && !error &&
            <span>{t("holdToSpeak", lang)}</span>}
        </div>

        {/* Error */}
        {error && (
          <div style={{ fontSize: 12, color: "var(--risk)", textAlign: "center" }}>{error}</div>
        )}

        {/* Result bubble */}
        {isDone && (transcript || reply) && (
          <div style={{ width: "100%", background: "var(--paper3)", borderRadius: 8,
            padding: "10px 14px", fontSize: 13 }}>
            {transcript && (
              <div style={{ marginBottom: 6 }}>
                <span style={{ fontSize: 10, color: "var(--ink3)", fontWeight: 700,
                  letterSpacing: ".06em", textTransform: "uppercase" }}>{t("youSaid", lang)}: </span>
                <span className="kn" style={{ color: "var(--ink)" }}>{transcript}</span>
              </div>
            )}
            {reply && (
              <div style={{ color: "var(--water2)", fontWeight: 600 }}>{reply}</div>
            )}
            <button type="button" onClick={reset}
              style={{ marginTop: 8, fontSize: 11, background: "none", border: "none",
                color: "var(--ink3)", cursor: "pointer", padding: 0, textDecoration: "underline" }}>
              {t("tryAgain", lang)}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
