// What the listen button says on each screen, in one place so Today can pre-generate
// Why's audio too. Indic Parler-TTS takes 9-20s on a sentence this long, and preloading
// only on mount meant arriving at Why and pressing listen immediately still waited.
import { verdict, outOfTen, advisoryHorizon } from "./api.js";
import { VERDICT, pick, tpl } from "../i18n/strings.js";

/** Whose field, what the forecast says, the number under it, and the crop action. */
export function todayNarration(d, lang) {
  const f = d.forecast;
  const state = VERDICT[verdict(f, d.skill).level];
  const adv = (f.advisories || [])[0];
  return [
    `${lang === "en" ? f.name_en : (f.name_kn || f.name_en)}, ${f.district_en}.`,
    pick(state.speak, lang),
    tpl("tenYears", lang, outOfTen(f.p_dry7.w1)),
    // Advisory payloads carry Kannada and English only. Never read English as if it
    // were Hindi or Telugu; the localized verdict above already carries the action.
    adv && (lang === "kn" || lang === "en")
      ? (lang === "kn" ? adv.action_kn : adv.action_en)
      : "",
  ].filter(Boolean).join(" ");
}

/** The evidence, how far ahead it is trusted, and where it came from. */
export function whyNarration(d, lang) {
  const ten = outOfTen(d.forecast.p_dry7.w1);
  const seasons = d.skill?.seasons_scored ?? null;
  const members = d.provenance_summary?.match(/(\d+)\s+ensemble members/)?.[1] ?? null;
  return [
    tpl("whySpoken", lang, seasons ?? "several", ten),
    tpl("outlookNote", lang, advisoryHorizon(d.skill)),
    tpl("whySources", lang, members),
  ].join(" ");
}
