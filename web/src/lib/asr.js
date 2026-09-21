// ASR server availability check — mirrors the pattern in speech.js for Parler TTS.

export const ASR_URL = import.meta.env.VITE_ASR_SERVER_URL || "http://localhost:8766";
// IndicConformer is an Indic-only checkpoint; English remains available for
// the rest of the UI/TTS but has no server-side ASR model behind it.
export const ASR_SUPPORTED_LANGS = ["kn", "hi", "te"];
export const ASR_INTERPRET_LANGS = [...ASR_SUPPORTED_LANGS, "en"];

export const normalizeSpeechLang = (lang) => {
  const code = String(lang || "kn").toLowerCase().split("-")[0];
  return ASR_INTERPRET_LANGS.includes(code) ? code : "kn";
};

export const browserSpeechRecognition = () =>
  typeof window !== "undefined" &&
  Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);

const LOCAL_INTENTS = {
  rain_yes: {
    kn: ["ಮಳೆ ಬಂತು", "ಮಳೆ ಬಿತ್ತು", "ಜೋರು ಮಳೆ", "ಸ್ವಲ್ಪ ಮಳೆ"],
    hi: ["बारिश हुई", "बारिश आई", "थोड़ी बारिश", "तेज बारिश"],
    te: ["వర్షం పడింది", "వర్షం వచ్చింది", "కొంచెం వర్షం", "భారీ వర్షం"],
    en: ["it rained", "rain today", "rained", "heavy rain", "light rain"],
  },
  rain_no: {
    kn: ["ಮಳೆ ಇಲ್ಲ", "ಮಳೆ ಬರಲಿಲ್ಲ", "ಮಳೆ ಆಗಲಿಲ್ಲ"],
    hi: ["बारिश नहीं", "बारिश नहीं हुई", "वर्षा नहीं"],
    te: ["వర్షం లేదు", "వర్షం పడలేదు", "వర్షం రాలేదు"],
    en: ["no rain", "did not rain", "no rainfall", "dry"],
  },
  advisory: {
    kn: ["ಬಿತ್ತನೆ", "ಸಲಹೆ", "ಏನು ಮಾಡಲಿ", "ಮಾಹಿತಿ"],
    hi: ["बुवाई", "सलाह", "क्या करूं", "जानकारी"],
    te: ["విత్తనాలు", "సలహా", "ఏమి చేయాలి", "సమాచారం"],
    en: ["sow", "sowing", "advice", "what to do", "advisory", "suggest"],
  },
  repeat: {
    kn: ["ಮತ್ತೆ", "ಮತ್ತೊಮ್ಮೆ", "ಮರುಕಳಿಸಿ"],
    hi: ["फिर से", "दोबारा", "फिर बोलो"],
    te: ["మళ్ళీ", "మరోసారి"],
    en: ["repeat", "again", "say again", "once more"],
  },
};

const LOCAL_REPLIES = {
  rain_yes: { kn: "ಧನ್ಯವಾದ. ನಿಮ್ಮ ಮಳೆ ವರದಿ ದಾಖಲಾಗಿದೆ.", hi: "धन्यवाद। आपकी बारिश की सूचना दर्ज हो गई।", te: "ధన్యవాదాలు. మీ వర్షం నివేదిక నమోదైంది.", en: "Thank you. Your rain report has been recorded." },
  rain_no: { kn: "ಧನ್ಯವಾದ. ಮಳೆ ಇಲ್ಲ ಎಂದು ದಾಖಲಾಗಿದೆ.", hi: "धन्यवाद। बारिश नहीं हुई, यह दर्ज हो गया।", te: "ధన్యవాదాలు. వర్షం లేదని నమోదైంది.", en: "Thank you. No rain today has been recorded." },
  advisory: { kn: "ಇಂದಿನ ಸಲಹೆ ತೆರೆಯಲಾಗಿದೆ. ದಯವಿಟ್ಟು ಕೇಳಿ ಬಟನ್ ಒತ್ತಿ.", hi: "आज की सलाह खुल गई है। कृपया सुनें बटन दबाएँ।", te: "నేటి సలహా తెరవబడింది. దయచేసి వినండి బటన్ నొక్కండి.", en: "Today's advisory is shown. Please tap the listen button." },
  repeat: { kn: "ಸಲಹೆ ಮತ್ತೆ ಓದಲಾಗುತ್ತಿದೆ.", hi: "सलाह फिर से पढ़ी जा रही है।", te: "సలహా మళ్ళీ చదవబడుతోంది.", en: "Repeating the advisory now." },
  unknown: { kn: "ಅರ್ಥವಾಗಲಿಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.", hi: "समझ में नहीं आया। फिर से कोशिश करें।", te: "అర్థం కాలేదు. మళ్ళీ ప్రయత్నించండి.", en: "I didn't understand. Please try again." },
};

function interpretLocally(transcript, lang) {
  const lower = transcript.toLocaleLowerCase();
  let action = "unknown";
  for (const [name, languages] of Object.entries(LOCAL_INTENTS)) {
    if ((languages[lang] || []).some((phrase) => lower.includes(phrase.toLocaleLowerCase()))) {
      action = name;
      break;
    }
  }
  return { transcript, lang, action, reply_text: LOCAL_REPLIES[action][lang] };
}

export const interpretTranscript = async (transcript, lang) => {
  try {
    const res = await fetch(`${ASR_URL}/interpret`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript, lang }),
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) throw new Error(`ASR interpretation error ${res.status}`);
    return res.json();
  } catch {
    // Browser STT remains useful when the local ASR process is unavailable.
    return interpretLocally(transcript, lang);
  }
};

let _asrAvailable = null;

export async function checkASRAvailable() {
  if (_asrAvailable !== null) return _asrAvailable;
  try {
    const res = await fetch(`${ASR_URL}/health`, { signal: AbortSignal.timeout(1200) });
    _asrAvailable = res.ok;
  } catch {
    _asrAvailable = false;
  }
  return _asrAvailable;
}

export const isASRAvailable = () => _asrAvailable === true;

// Kick off check immediately on import so it's cached before user taps mic.
if (typeof window !== "undefined") {
  checkASRAvailable().catch(() => {});
}
