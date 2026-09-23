import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getArea, verdict, outOfTen, advisoryHorizon } from "../lib/api.js";
import { loadPrefs } from "../lib/store.js";
import { VERDICT, S, t, tpl, pick, karteFor } from "../i18n/strings.js";
import { todayNarration } from "../lib/narration.js";
import Photo from "../components/Photo.jsx";
import Speak from "../components/Speak.jsx";
import Decade from "../components/Decade.jsx";
import Ribbon from "../components/Ribbon.jsx";
import Tabs from "../components/Tabs.jsx";
import { Shell, Msg, Rubric } from "../components/Frame.jsx";
import { Pin, Fwd, Tick } from "../components/Marks.jsx";
import LangSwitch from "../components/LangSwitch.jsx";
import MessageBell from "../components/MessageBell.jsx";
import VoiceAssistant from "../components/VoiceAssistant.jsx";

export default function Today() {
  const { areaId, lang, place } = loadPrefs();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => { getArea(areaId).then(setD).catch((e) => setErr(e.message)); }, [areaId]);


  if (err) return <Shell><Msg kind="failed" lang={lang} detail={err} /><Tabs lang={lang} /></Shell>;
  if (!d)  return <Shell><Msg kind="loading" lang={lang} /><Tabs lang={lang} /></Shell>;

  const f = d.forecast;
  const v = verdict(f, d.skill);
  const state = VERDICT[v.level];
  const horizon = advisoryHorizon(d.skill);
  const adv = (f.advisories || [])[0];
  const ten = outOfTen(f.p_dry7.w1);
  const karte = karteFor(d.meta.valid_from);

  const spoken = todayNarration(d, lang);

  return (
    <Shell>
      {/* place strip — quiet, small, answers "is this my field?" and nothing else */}
      <div className="pad rule-b" style={{ paddingTop: 11, paddingBottom: 10, display: "flex", alignItems: "center", gap: 9 }}>
        <Pin size={17} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="kn" style={{ fontSize: 17, fontWeight: 700, lineHeight: 1.15 }}>
            {lang === "en" ? f.name_en : (f.name_kn || f.name_en)}
          </div>
          {lang !== "en" && f.name_en ? <div className="gloss">{f.name_en}</div> : null}
          <div className="cap" style={{ fontSize: 11.5 }}>
            {/* hobli names are English-only upstream, so the Kannada anchor is the taluk */}
            {place?.taluk_kn ? <span className="kn" style={{ fontWeight: 600 }}>{place.taluk_kn} </span> : null}
            {place?.district_kn
              ? <span className="kn" style={{ fontWeight: 600 }}>{place.district_kn}</span>
              : f.district_en}
            {" · "}{new Date(d.meta.valid_from).toLocaleDateString("en-IN", { day: "numeric", month: "long" })}
            {karte ? <> · <span className="kn" style={{ fontWeight: 600 }}>{karte[lang] ?? karte.en} ಕಾರ್ತೆ</span></> : null}
          </div>
        </div>
        <MessageBell areaId={areaId} lang={lang} />
        <LangSwitch lang={lang} />
      </div>

      <div className="grow">
        <div className="spread">
          <div>
            {/* The photograph IS the forecast. It changes with the verdict, so the
                answer is legible before a single word is read. */}
            <Photo name={state.photo} lang={lang} className="-hero">
              <div className="on-photo">
                <div className="kn" style={{ fontSize: 23, fontWeight: 700, lineHeight: 1.2 }}>{pick(state.sit, lang)}</div>
                {lang !== "en" ? <div className="gloss gloss-on-photo" style={{ marginTop: 2 }}>{state.sit.en}</div> : null}
              </div>
            </Photo>

            {/* the one decision */}
            <div className="pad" style={{ paddingTop: 20, paddingBottom: 20 }}>
              <div className={`notice -${state.tone}`}>
                <div className="rubric">{t("whatToDo", "en")}</div>
                <div className="verdict" style={{ marginTop: 4 }}>{pick(state.act, lang)}</div>
                {lang !== "en" ? <div className="gloss" style={{ marginTop: 5, fontSize: 14 }}>{state.act.en}</div> : null}
              </div>

              {/* the reason, in the same breath as the decision — never a separate screen */}
              {/* the ten blocks below are the emphasis — the sentence stays plain,
                  which also keeps it translatable without markup surgery */}
              <div className="body-kn" style={{ marginTop: 16, color: "var(--ink2)" }}>
                {tpl("tenYears", lang, ten)}
              </div>
              <div className="gloss" style={{ marginTop: 4 }}>
                {tpl("tenYears", "en", ten)}
              </div>
              <div style={{ marginTop: 9 }}>
                <Decade n={ten} size="sm" tone={v.level === "high" ? "-risk" : ""}
                  label={`${ten} of 10 similar years had a week without rain`} />
              </div>

              <div style={{ marginTop: 18 }}>
                <Speak text={spoken} lang={lang} />
              </div>

              <VoiceAssistant lang={lang} areaId={areaId} pageDescription={spoken} />

            </div>
          </div>

          <div className="pad">
            <hr className="hr-heavy" />
            <div style={{ paddingTop: 16, paddingBottom: 20 }}>
              <Rubric en="The next four weeks">{t("nextFour", lang)}</Rubric>
              <Ribbon forecast={f} meta={d.meta} horizon={horizon} lang={lang} />
              <div className="gloss" style={{ marginTop: 12, display: "flex", gap: 16, flexWrap: "wrap" }}>
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 16, height: 3, background: "var(--ink)" }} /> {t("trustThis", "en")}
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 16, height: 0, borderTop: "2px dashed var(--ink3)" }} /> {t("outlook", "en")}
                </span>
              </div>
            </div>

            {adv ? (
              <>
                <hr className="hr" />
                <div style={{ paddingTop: 16, paddingBottom: 18 }}>
                  <div className={`notice -${state.tone}`}>
                    {/* The contract carries advisory text in Kannada and English only.
                        Keep the localized verdict as the primary message for Hindi
                        and Telugu, with the source advisory as the English gloss. */}
                    <div className="body-kn" style={{ fontSize: 19, fontWeight: 700, lineHeight: 1.45 }}>
                      {lang === "kn" ? adv.action_kn : pick(state.act, lang)}
                    </div>
                    <div className="gloss" style={{ marginTop: 4, fontSize: 13 }}>
                      {lang === "kn" ? adv.action_en : lang === "en" ? adv.action_en : `${adv.action_en} · ${pick(state.act, "en")}`}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 9, marginTop: 14, alignItems: "flex-start" }}>
                    <Tick size={17} />
                    <div>
                      <div className="kn" style={{ fontSize: 13.5, fontWeight: 700 }}>{t("govSays", lang)}</div>
                      <div className="gloss" style={{ fontSize: 11 }}>{adv.source.doc}, table {adv.source.table}</div>
                    </div>
                  </div>
                </div>
              </>
            ) : null}

            <hr className="hr" />
            <Link to="/why" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", minHeight: 62, gap: 10 }}>
              <span>
                <span className="h2">{S.whyTitle[lang] ?? S.whyTitle.en}</span>
                <span className="gloss" style={{ display: "block" }}>{S.whyTitle.en}</span>
              </span>
              <Fwd size={20} />
            </Link>
            <hr className="hr" />
          </div>
        </div>
      </div>
      <Tabs lang={lang} />
    </Shell>
  );
}
