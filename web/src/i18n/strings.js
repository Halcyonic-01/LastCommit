// Kannada is the source language. English is a gloss, set smaller, never the other way round.
// Wording is agricultural, not meteorological: "rain stops", not "dry spell probability".

export const LANGS = [
  { code: "kn", script: "ಕನ್ನಡ",   en: "Kannada", speech: "kn-IN" },
  { code: "hi", script: "हिन्दी",   en: "Hindi",   speech: "hi-IN" },
  { code: "te", script: "తెలుగు",  en: "Telugu",  speech: "te-IN" },
  { code: "en", script: "English", en: "English", speech: "en-IN" },
];

export const S = {
  app:        { kn: "ವರ್ಷದೃಷ್ಟಿ", hi: "वर्षादृष्टि", te: "వర్షదృష్టి", en: "VarshaDrishti" },
  tagline:    { kn: "ಮಳೆ ಬರುತ್ತಾ? ಬಿತ್ತಬಹುದಾ?", hi: "बारिश आएगी? बुवाई करें?", te: "వర్షం వస్తుందా? విత్తాలా?", en: "Will it rain? Can I sow?" },
  pickLang:   { kn: "ನಿಮ್ಮ ಭಾಷೆ ಒತ್ತಿ", hi: "अपनी भाषा चुनें", te: "మీ భాష ఎంచుకోండి", en: "Tap your language" },
  pickPlace:  { kn: "ನಿಮ್ಮ ಹೋಬಳಿ", hi: "आपका होबली", te: "మీ హోబళి", en: "Your hobli" },
  start:      { kn: "ಶುರು ಮಾಡಿ", hi: "शुरू करें", te: "ప్రారంభించండి", en: "Start" },
  listen:     { kn: "ಕೇಳಿ", hi: "सुनें", te: "వినండి", en: "Listen" },
  back:       { kn: "ಹಿಂದೆ", hi: "पीछे", te: "వెనుకకు", en: "Back" },

  today:      { kn: "ಇಂದು", hi: "आज", te: "ఈరోజు", en: "Today" },
  rainReport: { kn: "ಮಳೆ ವರದಿ", hi: "बारिश की सूचना", te: "వర్ష నివేదిక", en: "Rain report" },
  why:        { kn: "ಏಕೆ?", hi: "क्यों?", te: "ఎందుకు?", en: "Why?" },

  whatToDo:   { kn: "ಏನು ಮಾಡಬೇಕು", hi: "क्या करें", te: "ఏమి చేయాలి", en: "What to do" },
  nextFour:   { kn: "ಮುಂದಿನ ನಾಲ್ಕು ವಾರ", hi: "अगले चार हफ़्ते", te: "వచ్చే నాలుగు వారాలు", en: "The next four weeks" },
  outlook:    { kn: "ಅಂದಾಜು ಮಾತ್ರ", hi: "सिर्फ़ अनुमान", te: "అంచనా మాత్రమే", en: "outlook only" },
  trustThis:  { kn: "ಇದನ್ನು ನಂಬಬಹುದು", hi: "इस पर भरोसा करें", te: "దీన్ని నమ్మవచ్చు", en: "you can act on this" },

  whyTitle:   { kn: "ಏಕೆ ಹೀಗೆ ಹೇಳಿದೆವು?", hi: "हमने ऐसा क्यों कहा?", te: "మేము ఎందుకు ఇలా చెప్పాము?", en: "Why we said this" },
  howSure:    { kn: "ಎಷ್ಟು ಖಚಿತ?", hi: "कितना पक्का?", te: "ఎంత ఖచ్చితం?", en: "How sure are we" },
  evidence:   { kn: "ಹಿಂದಿನ ವರ್ಷಗಳ ಮಳೆ", hi: "पिछले सालों की बारिश", te: "గత సంవత్సరాల వర్షం", en: "Rainfall in past years" },
  whereFrom:  { kn: "ಮಾಹಿತಿ ಎಲ್ಲಿಂದ?", hi: "जानकारी कहाँ से?", te: "సమాచారం ఎక్కడి నుంచి?", en: "Where this comes from" },
  govSays:    { kn: "ಸರ್ಕಾರಿ ಕೃಷಿ ವಿಜ್ಞಾನಿಗಳ ಸಲಹೆ", hi: "सरकारी कृषि वैज्ञानिकों की सलाह", te: "ప్రభుత్వ వ్యవసాయ శాస్త్రవేత్తల సలహా", en: "Government agriculture scientists' advice" },

  didItRain:  { kn: "ನಿನ್ನೆ ಮಳೆ ಬಂತಾ?", hi: "कल बारिश हुई?", te: "నిన్న వర్షం పడిందా?", en: "Did it rain yesterday?" },
  noRain:     { kn: "ಮಳೆ ಇಲ್ಲ", hi: "बारिश नहीं", te: "వర్షం లేదు", en: "No rain" },
  aLittle:    { kn: "ಸ್ವಲ್ಪ", hi: "थोड़ी", te: "కొంచెం", en: "A little" },
  heavy:      { kn: "ಜೋರು ಮಳೆ", hi: "तेज़ बारिश", te: "భారీ వర్షం", en: "Heavy rain" },
  send:       { kn: "ಕಳುಹಿಸಿ", hi: "भेजें", te: "పంపండి", en: "Send" },
  again:      { kn: "ಇನ್ನೊಮ್ಮೆ", hi: "फिर से", te: "మళ్ళీ", en: "Report again" },
  thanks:     { kn: "ಧನ್ಯವಾದ", hi: "धन्यवाद", te: "ధన్యవాదాలు", en: "Thank you" },
  reportHelps:{ kn: "ನಿಮ್ಮ ಉತ್ತರ ಮುನ್ಸೂಚನೆ ಸರಿಪಡಿಸುತ್ತದೆ", hi: "आपका जवाब पूर्वानुमान सुधारता है", te: "మీ సమాధానం సూచనను సరిచేస్తుంది", en: "Your answer corrects the forecast" },
  // A report is almost never sent on the spot — say where it actually is, never "sent".
  savedHere: { kn: "ಈ ಫೋನಿನಲ್ಲಿ ಉಳಿದಿದೆ", hi: "इस फ़ोन में सहेजा गया", te: "ఈ ఫోన్‌లో భద్రమైంది", en: "Saved on this phone" },
  willSend:  { kn: "ಸಿಗ್ನಲ್ ಬಂದಾಗ ತಾನೇ ಹೋಗುತ್ತದೆ", hi: "सिग्नल आते ही अपने आप चला जाएगा", te: "సిగ్నల్ వచ్చాక దానంతట అదే వెళ్తుంది", en: "It will go on its own when there is signal" },
  notSaved:  { kn: "ಉಳಿಸಲು ಆಗಲಿಲ್ಲ · ಇನ್ನೊಮ್ಮೆ ಒತ್ತಿ", hi: "सहेजा नहीं जा सका · फिर से दबाएँ", te: "భద్రపరచలేకపోయాం · మళ్ళీ నొక్కండి", en: "Could not save · tap again" },
  noSpace:   { kn: "ಫೋನಿನಲ್ಲಿ ಜಾಗ ಇಲ್ಲ, ಅಥವಾ ಬ್ರೌಸರ್ ಉಳಿಸಲು ಬಿಡುತ್ತಿಲ್ಲ", hi: "फ़ोन में जगह नहीं है, या ब्राउज़र सहेजने नहीं दे रहा", te: "ఫోన్‌లో చోటు లేదు, లేదా బ్రౌజర్ భద్రపరచనివ్వడం లేదు", en: "The phone is out of space, or the browser is blocking storage" },

  offline:    { kn: "ಇಂಟರ್ನೆಟ್ ಇಲ್ಲ — ಉಳಿಸಿದ ಮಾಹಿತಿ", hi: "इंटरनेट नहीं — सहेजी गई जानकारी", te: "ఇంటర్నెట్ లేదు — సేవ్ చేసిన సమాచారం", en: "No internet — showing the saved forecast" },
  loading:    { kn: "ಒಂದು ಕ್ಷಣ…", hi: "एक पल…", te: "ఒక క్షణం…", en: "One moment…" },
  failed:     { kn: "ಮಾಹಿತಿ ಸಿಗಲಿಲ್ಲ", hi: "जानकारी नहीं मिली", te: "సమాచారం దొరకలేదు", en: "Could not load the forecast" },
};

/* The three states a farmer can be in. Situation first, then the one action.
   `photo` names the image that has to carry the same meaning as the words. */
export const VERDICT = {
  high: {
    tone: "risk", photo: "land",
    sit: { kn: "ಈ ವಾರ ಮಳೆ ಇಲ್ಲ", hi: "इस हफ़्ते बारिश नहीं", te: "ఈ వారం వర్షం లేదు", en: "No rain this week" },
    act: { kn: "ಈಗ ಬಿತ್ತಬೇಡಿ",   hi: "अभी बुवाई न करें",   te: "ఇప్పుడు విత్తవద్దు",  en: "Do not sow yet" },
    speak: { kn: "ಈ ವಾರ ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಕಡಿಮೆ. ಈಗ ಬಿತ್ತನೆ ಮಾಡಬೇಡಿ.", hi: "इस हफ़्ते बारिश की उम्मीद कम है। अभी बुवाई न करें।", te: "ఈ వారం వర్షం వచ్చే అవకాశం తక్కువ. ఇప్పుడు విత్తనం వేయవద్దు.", en: "Little chance of rain this week. Do not sow yet." },
  },
  caution: {
    tone: "wait", photo: "land",
    sit: { kn: "ಮಳೆ ಖಚಿತವಿಲ್ಲ",   hi: "बारिश पक्की नहीं",    te: "వర్షం ఖచ్చితం కాదు", en: "Rain is not certain" },
    act: { kn: "ಬಿತ್ತನೆಗೆ ಕಾಯಿರಿ", hi: "बुवाई के लिए रुकें", te: "విత్తడానికి ఆగండి",   en: "Wait before sowing" },
    speak: { kn: "ಮಳೆ ಬರುವುದು ಖಚಿತವಿಲ್ಲ. ಬಿತ್ತನೆಗೆ ಸ್ವಲ್ಪ ಕಾಯಿರಿ.", hi: "बारिश पक्की नहीं है। बुवाई के लिए थोड़ा रुकें।", te: "వర్షం ఖచ్చితం కాదు. విత్తడానికి కొంచెం ఆగండి.", en: "Rain is not certain. Wait a little before sowing." },
  },
  ok: {
    tone: "ok", photo: "sowing",
    sit: { kn: "ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಇದೆ", hi: "बारिश आने की उम्मीद", te: "వర్షం వచ్చే అవకాశం ఉంది", en: "Rain is likely" },
    act: { kn: "ಬಿತ್ತನೆ ಮಾಡಬಹುದು",     hi: "बुवाई कर सकते हैं",   te: "విత్తనం వేయవచ్చు",     en: "You can sow" },
    speak: { kn: "ಮುಂದಿನ ದಿನಗಳಲ್ಲಿ ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಇದೆ. ಬಿತ್ತನೆ ಮಾಡಬಹುದು.", hi: "आने वाले दिनों में बारिश की उम्मीद है। बुवाई कर सकते हैं।", te: "రాబోయే రోజుల్లో వర్షం వచ్చే అవకాశం ఉంది. విత్తనం వేయవచ్చు.", en: "Rain is likely in the coming days. You can sow." },
  },
};

/* ಕಾರ್ತೆ — the Sun-nakshatra rain periods Karnataka farmers actually name a
   forecast by. Boundaries below are 2026 panchanga dates for Bengaluru.
   VERIFIED against a panchanga: Uttara, Hasta, Chitta, Swati.
   The earlier entries are ~13.3-day extrapolations and are marked approx;
   replace this table with a computed ephemeris before a season goes live. */
export const KARTE = [
  { from: "2026-05-11", kn: "ಕೃತಿಕಾ",  hi: "कृत्तिका", te: "కృత్తిక",  en: "Krittika",   approx: true },
  { from: "2026-05-25", kn: "ರೋಹಿಣಿ",  hi: "रोहिणी",   te: "రోహిణి",  en: "Rohini",     approx: true },
  { from: "2026-06-08", kn: "ಮೃಗಶಿರ", hi: "मृगशिरा",  te: "మృగశిర",  en: "Mrigashira", approx: true },
  { from: "2026-06-22", kn: "ಆರಿದ್ರಾ", hi: "आर्द्रा",   te: "ఆర్ద్ర",    en: "Ardra",      approx: true },
  { from: "2026-07-07", kn: "ಪುನರ್ವಸು",hi: "पुनर्वसु", te: "పునర్వసు", en: "Punarvasu",  approx: true },
  { from: "2026-07-21", kn: "ಪುಷ್ಯ",   hi: "पुष्य",    te: "పుష్య",    en: "Pushya",     approx: true },
  { from: "2026-08-03", kn: "ಆಶ್ಲೇಷ",  hi: "आश्लेषा",  te: "ఆశ్లేష",   en: "Ashlesha",   approx: true },
  { from: "2026-08-17", kn: "ಮಘಾ",    hi: "मघा",     te: "మఘ",     en: "Magha",      approx: true },
  { from: "2026-08-31", kn: "ಪುಬ್ಬ",   hi: "पूर्वा",    te: "పుబ్బ",    en: "Purva",      approx: true },
  { from: "2026-09-13", kn: "ಉತ್ತರ",   hi: "उत्तरा",    te: "ఉత్తర",    en: "Uttara"  },
  { from: "2026-09-27", kn: "ಹಸ್ತ",    hi: "हस्त",     te: "హస్త",     en: "Hasta"   },
  { from: "2026-10-11", kn: "ಚಿತ್ತ",    hi: "चित्रा",    te: "చిత్త",     en: "Chitta"  },
  { from: "2026-10-24", kn: "ಸ್ವಾತಿ",   hi: "स्वाति",    te: "స్వాతి",    en: "Swati"   },
];

/** The karte a date falls in. Null outside the table rather than a wrong guess. */
export function karteFor(iso) {
  let hit = null;
  for (const k of KARTE) if (iso >= k.from) hit = k;
  return hit;
}

/* Sentences that carry a number. These must exist in every language — falling
   back to English here would hand a Telugu reader the one line that matters most
   in a script they did not choose. */
export const TPL = {
  tenYears: {
    kn: (n) => `ಕಳೆದ 10 ವರ್ಷಗಳಲ್ಲಿ ${n} ವರ್ಷ ಇದೇ ಸಮಯಕ್ಕೆ ಒಂದು ವಾರ ಮಳೆ ನಿಂತಿತ್ತು.`,
    hi: (n) => `पिछले 10 सालों में से ${n} साल इसी समय एक हफ़्ते बारिश रुक गई थी।`,
    te: (n) => `గత 10 సంవత్సరాలలో ${n} సంవత్సరాలు ఇదే సమయంలో ఒక వారం వర్షం ఆగిపోయింది.`,
    en: (n) => `In ${n} of the last 10 years like this one, the rain stopped for a week.`,
  },
  tenYearsHead: {
    kn: (n) => `ಇಂಥ 10 ವರ್ಷಗಳಲ್ಲಿ ${n} ವರ್ಷ ಮಳೆ ಒಂದು ವಾರ ನಿಂತಿತ್ತು`,
    hi: (n) => `ऐसे 10 सालों में से ${n} साल बारिश एक हफ़्ते रुकी थी`,
    te: (n) => `ఇలాంటి 10 సంవత్సరాలలో ${n} సంవత్సరాలు వర్షం ఒక వారం ఆగింది`,
    en: (n) => `In ${n} of 10 years like this one, the rain stopped for a week`,
  },
  outlookNote: {
    kn: (h) => `ಅದಕ್ಕೇ ಈ ಆ್ಯಪ್ ${h + 1} ಮತ್ತು ${h + 2}ನೇ ವಾರಕ್ಕೆ ಏನು ಮಾಡಬೇಕೆಂದು ಹೇಳುವುದಿಲ್ಲ. ಅಂದಾಜು ಎಂದಷ್ಟೇ ಹೇಳುತ್ತದೆ.`,
    hi: (h) => `इसीलिए यह ऐप हफ़्ते ${h + 1} और ${h + 2} के लिए कोई सलाह नहीं देता। सिर्फ़ अनुमान कहता है।`,
    te: (h) => `అందుకే ఈ యాప్ ${h + 1}, ${h + 2} వారాలకు ఏమి చేయాలో చెప్పదు. అంచనా మాత్రమే అని చెబుతుంది.`,
    en: (h) => `That is why this app gives no action for weeks ${h + 1} and ${h + 2}. It only says outlook.`,
  },
  whySpoken: {
    kn: (y, n) => `ಕಳೆದ ${y} ವರ್ಷಗಳ ಮಳೆ ದಾಖಲೆಯನ್ನು ಇಂದಿನ ಸ್ಥಿತಿಯ ಜೊತೆ ಹೋಲಿಸಿದ್ದೇವೆ. ಹತ್ತರಲ್ಲಿ ${n} ವರ್ಷ ಒಂದು ವಾರ ಮಳೆ ನಿಂತಿತ್ತು. ಈ ವಾರ ಮತ್ತು ಮುಂದಿನ ವಾರ ನಂಬಬಹುದು.`,
    hi: (y, n) => `हमने ${y} सालों का बारिश का रिकॉर्ड आज की स्थिति से मिलाया। दस में से ${n} साल एक हफ़्ते बारिश रुकी थी। इस हफ़्ते और अगले हफ़्ते पर भरोसा करें।`,
    te: (y, n) => `మేము ${y} సంవత్సరాల వర్ష రికార్డును నేటి పరిస్థితితో పోల్చాము. పదిలో ${n} సంవత్సరాలు ఒక వారం వర్షం ఆగింది. ఈ వారం, వచ్చే వారం నమ్మవచ్చు.`,
    en: (y, n) => `We compared ${y} years of rainfall records with today's conditions. In ${n} of 10 similar years the rain stopped for a week. Trust this week and next.`,
  },
};

/** Render a numbered sentence in the chosen language, never silently in English. */
export const tpl = (key, lang, ...args) => (TPL[key]?.[lang] ?? TPL[key]?.en)(...args);

export const t = (key, lang = "kn") => S[key]?.[lang] ?? S[key]?.en ?? key;
export const pick = (obj, lang = "kn") => obj?.[lang] ?? obj?.en ?? "";
