import { useState, useRef, useEffect } from "react";
import { speakSequence, checkParlerAvailable, unlockAudio,
         primePrerendered, prerenderedFile } from "../lib/speech.js";
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
export default function VoiceAssistant({ lang = "kn", areaId, pageDescription = "", advisoryKn = "" }) {
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
  const clipRef = useRef(null);   // real <audio> in the DOM — see Speak.jsx

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

  // Browser recognition streams and returns in well under a second; IndicConformer on
  // CPU takes several. Prefer the fast one and keep the local server as the fallback —
  // the watchdog below is what makes that safe when the browser service goes quiet.
  const useLocalASR = !browserSpeechRecognition() && asr === true;
  if (asr === null) return null;                              // still probing
  if (!useLocalASR && !browserSpeechRecognition()) return null; // no way to listen at all

  // What to say back, in order. The reply goes first because for "advisory" it is the
  // CRIDA action and plays instantly from a pre-rendered clip; the page narration follows
  // so the farmer hears this screen's own numbers without pressing anything else.
  const spokenFor = (data) => {
    if (data.action === "repeat") return [pageDescription || data.reply_text || ""];
    const reply = data.reply_text || "";
    if (!(data.action === "advisory" || data.action === "unknown")) return [reply].filter(Boolean);
    // Today's narration already ends with the same CRIDA sentence the reply uses. Say the
    // reply first because it plays instantly from a clip, then the rest of the page once.
    const bare = reply.replace(/[.।]+$/, "").trim();
    const rest = bare && pageDescription.includes(bare)
      ? pageDescription.replace(bare, "").replace(/\s+/g, " ").trim()
      : pageDescription;
    return [reply, rest].filter(Boolean);
  };

  const finishTranscript = async (heard) => {
    if (!heard.trim()) {
      fail("I could not hear a clear answer. Please try again.");
      return;
    }
    // This screen's own advisory, spoken immediately. /interpret only ever returns the
    // same sentence back, so waiting for that round trip before making a sound is pure
    // delay — the clip starts now and the text fills in behind it.
    const played = Boolean(clipRef.current);   // the clip already started on release
    try {
      const data = await interpretTranscript(heard, lang);
      clearStall();
      setTranscript(data.transcript || heard);
      setReply(data.reply_text || "");
      setState("done");
      checkParlerAvailable();
      const lines = spokenFor(data);
      // The clip already covered the first line; do not say it twice.
      speakSequence(played ? lines.slice(1) : lines, lang);
    } catch {
      fail("Could not understand the recording. Please try again.");
    }
  };

  const startRecording = async () => {
    // Must run synchronously on the press: by the time the reply arrives the gesture
    // has expired and Chrome refuses to start an AudioContext, which is exactly how
    // the assistant ended up returning success while making no sound at all.
    unlockAudio();
    primePrerendered();   // must be on the press — see speech.js
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
    // First statement, inside the pointer-up handler, nothing awaited before it. This
    // is the demo's answer and the only arrangement a browser will not refuse.
    const el = clipRef.current;
    if (el) {
      try { el.currentTime = 0; } catch { /* not seekable yet */ }
      el.play().catch(() => {});
    }
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
      checkParlerAvailable();
      speakSequence(spokenFor(data), lang);
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

  const clipFile = prerenderedFile(advisoryKn, lang);
  const isListening = state === "listening";
  const isProcessing = state === "processing";
  const isDone = state === "done";

  return (
    <div style={{ marginTop: 20, borderTop: "1px solid var(--rule2)", paddingTop: 16 }}>
      {clipFile ? <audio ref={clipRef} src={clipFile} preload="auto" /> : null}

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
