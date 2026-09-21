// Reads the frozen P1 contract. Nothing here knows how a forecast is produced.
async function json(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export const getIndex  = () => json("/forecast/index.json");
export const getArea   = (areaId) => json(`/forecast/area/${areaId}.json`);
export const getLatest = () => json("/forecast/latest.json");

export const LEADS = ["w1", "w2", "w3", "w4"];

/** Display the actual forecast window rather than a hardcoded +1/+2 label. */
export function dateRangeLabel(range, locale = "en-IN") {
  if (!range?.start || !range?.end) return "";
  const opts = { day: "numeric", month: "short" };
  const start = new Date(`${range.start}T00:00:00`).toLocaleDateString(locale, opts);
  const end = new Date(`${range.end}T00:00:00`).toLocaleDateString(locale, opts);
  return `${start} – ${end}`;
}

/** Leads we are allowed to advise on. Past this the contract only permits "outlook".
 *  0 when skill is missing — treat nothing as advisable rather than guess a week
 *  count that was last true under a retired backend and is silently stale today. */
export const advisoryHorizon = (skill) => skill?.advisory_horizon_weeks ?? 0;

/** Highest dry-spell risk inside the advisory horizon — this drives the one decision. */
export function verdict(forecast, skill) {
  const h = advisoryHorizon(skill);
  const within = LEADS.slice(0, h).map((k) => forecast.p_dry7[k]);
  const p = Math.max(...within);
  const lead = LEADS[within.indexOf(p)];
  if (p >= 0.5) return { level: "high", p, lead };
  if (p >= 0.25) return { level: "caution", p, lead };
  return { level: "ok", p, lead };
}

/** Frequency framing. Lay readers judge "3 in 10" far better than "32%". */
export const outOfTen = (p) => Math.max(0, Math.min(10, Math.round(p * 10)));

/** Plain-language skill word per lead — the same honesty the officer screen shows. */
const WORDS = {
  good: { kn: "ಚೆನ್ನಾಗಿ ನಂಬಬಹುದು", hi: "पूरा भरोसा करें", te: "బాగా నమ్మవచ్చు", en: "clearly better than guessing" },
  fair: { kn: "ನಂಬಬಹುದು",          hi: "भरोसा करें",      te: "నమ్మవచ్చు",     en: "better than guessing" },
  weak: { kn: "ಅಂದಾಜು ಮಾತ್ರ",       hi: "सिर्फ़ अनुमान",    te: "అంచనా మాత్రమే", en: "barely better than guessing" },
  none: { kn: "ನಂಬಬೇಡಿ",           hi: "भरोसा न करें",    te: "నమ్మవద్దు",     en: "no better than guessing" },
};

export function skillWord(bss) {
  if (bss >= 0.15) return WORDS.good;
  if (bss >= 0.05) return WORDS.fair;
  if (bss >= 0)    return WORDS.weak;
  return WORDS.none;
}
