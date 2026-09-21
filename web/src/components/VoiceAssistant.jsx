import { useState, useRef, useEffect } from "react";
import { speak, checkParlerAvailable } from "../lib/speech.js";
import { t } from "../i18n/strings.js";
import {
  isASRAvailable, checkASRAvailable, ASR_URL,
  browserSpeechRecognition, interpretTranscript, normalizeSpeechLang,
} from "../lib/asr.js";

// Nothing may leave the user stuck: every path that starts a spinner arms this, and
// firing it always lands back on idle with a message. Long enough for a slow first
// Parler load, short enough that a demo does not look frozen.
const STALL_MS = 20000;

/**
 * Hold-to-speak voice assistant for the farmer.
 *
 * Two ways to hear the farmer, in this order:
 *   1. services/asr/server.py — IndicConformer, on this machine, works offline.
 *   2. the browser's own SpeechRecognition — needs a route to Google's speech
 *      service, so it is the fallback rather than the default.
 * Then /interpret maps the words to an intent and a reply, and speech.js speaks it.
 */
export default function VoiceAssistant({ lang = "kn", areaId, pageDescription = "" }) {
  lang = normalizeSpeechLang(lang);
  const [asr, setAsr] = useState(isASRAvailable() ? true : null); // null = still probing
  const [state, setState] = useState("idle"); // idle | listening | processing | done
  const [transcript, setTranscript] = useState("");
  const [reply, setReply] = useState("");
  const [error, setError] = useState("");

  const recorderRef = useRef(null);
  const recognitionRef = useRef(null);
  const browserTranscriptRef = useRef("");
  const chunksRef = useRef([]);
  const stallRef = useRef(null);

  useEffect(() => {
    checkASRAvailable().then(setAsr).catch(() => setAsr(false));
  }, []);

  const clearStall = () => { clearTimeout(stallRef.current); stallRef.current = null; };
  useEffect(() => clearStall, []);

  const fail = (message) => {
    clearStall();
    setError(message);
    setState("idle");
  };

  // Arm the watchdog whenever we hand control to something that may never call back:
  // the browser speech service can accept start() and then go quiet, and the button is
  // disabled while processing, so without this the screen is dead until a reload.
  const armStall = (message) => {
    clearStall();
    stallRef.current = setTimeout(() => fail(message), STALL_MS);
  };

  // The local server is preferred: it is this project's own model, it needs no internet,
  // and it is the one we can actually keep running for a demo.
  const useLocalASR = asr === true;
  if (asr === null) return null;                              // still probing
  if (!useLocalASR && !browserSpeechRecognition()) return null; // no way to listen at all

  // What to say back. "repeat" means read the page; every other intent already has its
  // own reply, and for "advisory" that reply IS the CRIDA advice — reading the whole page
  // on top of it just made the answer long enough to need a pre-rendered clip to hide it.
  const spokenFor = (data) =>
    data.action === "repeat" ? (pageDescription || data.reply_text || "") : (data.reply_text || "");

  const finishTranscript = async (heard) => {
    if (!heard.trim()) {
      fail("I could not hear a clear answer. Please try again.");
      return;
    }
    try {
      const data = await interpretTranscript(heard, lang);
      clearStall();
      setTranscript(data.transcript || heard);
      setReply(data.reply_text || "");
      setState("done");
      const spokenResponse = spokenFor(data);
      if (spokenResponse) {
        await checkParlerAvailable();
        await speak(spokenResponse, lang);
      }
    } catch {
      fail("Could not understand the recording. Please try again.");
    }
  };

  const startRecording = async () => {
    setError("");
    setTranscript("");
    setReply("");
    try {
      if (!useLocalASR) {
        const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new Recognition();
        recognition.lang = `${lang}-IN`;
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;
        browserTranscriptRef.current = "";
        recognition.onresult = (event) => {
          let text = "";
          for (let i = 0; i < event.results.length; i += 1) {
            text += `${event.results[i][0].transcript} `;
          }
          // Keep the latest complete phrase; interim text is still useful if
          // the browser closes the session before emitting a final result.
          browserTranscriptRef.current = text.trim();
        };
        recognition.onerror = (e) => {
          recognitionRef.current = null;
          fail(e?.error === "not-allowed"
            ? "Microphone permission is blocked for this site."
            : "Speech was not recognised. Please try again.");
        };
        recognition.onend = () => {
          recognitionRef.current = null;
          const heard = browserTranscriptRef.current.trim();
          if (heard) finishTranscript(heard);
          else fail("Please speak a little longer, then try again.");
        };
        recognitionRef.current = recognition;
        recognition.start();
        setState("listening");
        // The browser service can accept start() and then never call back at all.
        armStall("The browser speech service did not respond. Please try again.");
        return;
      }
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        throw new Error("Audio recording is not supported by this browser");
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const mimeTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/ogg;codecs=opus",
        "audio/mp4",
      ];
      const mimeType = mimeTypes.find((type) => MediaRecorder.isTypeSupported?.(type)) || "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorderRef.current = recorder;
      recorder.start(100); // collect every 100ms
      setState("listening");
    } catch {
      fail("Microphone access denied.");
    }
  };

  const stopRecording = async () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      setState("processing");
      armStall("That took too long. Please try again.");
      return;
    }
    const recorder = recorderRef.current;
    // Nothing is running — the recogniser may have ended on its own while the button was
    // still held. Returning here used to leave a disabled spinner on screen forever.
    if (!recorder || recorder.state === "inactive") {
      if (state === "listening") setState("idle");
      return;
    }
    setState("processing");
    armStall("That took too long. Please try again.");

    await new Promise((resolve) => {
      recorder.onstop = resolve;
      recorder.stop();
      recorder.stream.getTracks().forEach((t) => t.stop());
    });

    const mimeType = recorder.mimeType || "audio/webm";
    const blob = new Blob(chunksRef.current, { type: mimeType });
    if (blob.size < 500) {
      fail("Audio too short. Hold the button and speak.");
      return;
    }

    try {
      const form = new FormData();
      const extension = mimeType.includes("ogg") ? "ogg" : mimeType.includes("mp4") ? "mp4" : "webm";
      form.append("audio", blob, `recording.${extension}`);
      const res = await fetch(`${ASR_URL}/transcribe`, {
        method: "POST",
        headers: { "X-Lang": lang },
        body: form,
        signal: AbortSignal.timeout(30000),
      });
      if (!res.ok) throw new Error(`ASR error ${res.status}`);
      const data = await res.json();
      if (!(data.transcript || "").trim()) {
        fail("I could not hear a clear answer. Please try again.");
        return;
      }
      clearStall();
      setTranscript(data.transcript);
      setReply(data.reply_text || "");
      setState("done");
      const spokenResponse = spokenFor(data);
      if (spokenResponse) {
        await checkParlerAvailable();
        await speak(spokenResponse, lang);
      }
    } catch {
      fail("Could not reach the speech server on this machine.");
    }
  };

  const reset = () => {
    clearStall();
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
          onPointerCancel={isListening ? stopRecording : undefined}
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

        {/* The mic is disabled while processing, so this is the only way back out
            before the watchdog fires. Without one, a slow reply feels like a crash. */}
        {isProcessing && (
          <button type="button" onClick={reset}
            style={{ fontSize: 11, background: "none", border: "none", color: "var(--ink3)",
              cursor: "pointer", padding: 0, textDecoration: "underline" }}>
            {t("tryAgain", lang)}
          </button>
        )}

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
