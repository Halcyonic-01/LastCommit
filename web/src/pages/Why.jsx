import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getArea, LEADS, outOfTen, advisoryHorizon, skillWord } from "../lib/api.js";
import { loadPrefs } from "../lib/store.js";
import { S, t, tpl, karteFor } from "../i18n/strings.js";
import Photo from "../components/Photo.jsx";
import Speak from "../components/Speak.jsx";
import Decade from "../components/Decade.jsx";
import Tabs from "../components/Tabs.jsx";
import { Shell, Msg, Rubric } from "../components/Frame.jsx";
import { Back } from "../components/Marks.jsx";
import LangSwitch from "../components/LangSwitch.jsx";
import { whyNarration } from "../lib/narration.js";

export default function Why() {
  const nav = useNavigate();
  const { areaId, lang } = loadPrefs();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { getArea(areaId).then(setD).catch((e) => setErr(e.message)); }, [areaId]);

  if (err) return <Shell><Msg kind="failed" lang={lang} detail={err} /><Tabs lang={lang} /></Shell>;
  if (!d)  return <Shell><Msg kind="loading" lang={lang} /><Tabs lang={lang} /></Shell>;

  const f = d.forecast;
  const ten = outOfTen(f.p_dry7.w1);
  // Real, structured fields only. provenance_summary is prose for a sentence, not a
  // number source — regex-parsing it for "34" cost us the actual season count once
  // already (it was hardcoded to the retired 34-LOYO methodology's number and never
  // updated), so anything this page states as a fact reads it directly instead.
  const seasons = d.skill?.seasons_scored ?? null;
  const members = d.provenance_summary?.match(/(\d+)\s+ensemble members/)?.[1] ?? null;
  const horizon = advisoryHorizon(d.skill);

  const spoken = whyNarration(d, lang);

  return (
    <Shell>
      <div className="pad rule-b" style={{ paddingTop: 8, paddingBottom: 8, display: "flex", alignItems: "center", gap: 10 }}>
        <button type="button" onClick={() => nav(-1)} aria-label={`${t("back", lang)} — back`}
          style={{ width: 46, height: 46, display: "flex", alignItems: "center", justifyContent: "center", marginLeft: -12 }}>
          <Back size={21} />
        </button>
        <div style={{ flex: 1 }}>
          <div className="h2">{S.whyTitle[lang] ?? S.whyTitle.en}</div>
          <div className="gloss">{S.whyTitle.en}</div>
        </div>
        <Speak text={spoken} lang={lang} variant="icon" />
        <LangSwitch lang={lang} />
      </div>

      <div className="grow">
        <div className="spread pad" style={{ paddingTop: 22, paddingBottom: 24 }}>
          <div>
            {/* The evidence, stated as a sentence a person would say out loud. */}
            <div className="rubric">Evidence · {seasons ?? "—"} seasons</div>
            <h1 className="kn" style={{ fontSize: 30, fontWeight: 800, lineHeight: 1.22, margin: "6px 0 0" }}>
              {tpl("tenYearsHead", lang, ten)}
            </h1>
            <div className="gloss" style={{ marginTop: 5 }}>
              {tpl("tenYearsHead", "en", ten)}
            </div>
            <div style={{ marginTop: 16 }}>
              <Decade n={ten} size="lg" tone="-risk" label={`${ten} of 10 similar years had a week-long dry spell`} />
            </div>
            <div className="gloss" style={{ marginTop: 10, display: "flex", gap: 18, flexWrap: "wrap" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 11, height: 11, background: "var(--risk)" }} /> rain stopped
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 11, height: 11, background: "var(--rule)" }} /> rain continued
              </span>
            </div>


            {/* A figure, captioned like a figure in a printed report. */}
            <figure style={{ margin: "26px 0 0" }}>
              <Photo name="drought" lang={lang} height={190} scrim={false} credit={false} />
              <figcaption className="gloss" style={{ marginTop: 8, borderLeft: "2px solid var(--rule2)", paddingLeft: 10 }}>
                A week without rain after sowing is what ruins the crop — not the season total.
                Karnataka, 2012. Photo: Pushkarv, CC BY-SA 3.0.
              </figcaption>
            </figure>
          </div>

          <div>
            <hr className="hr-heavy" style={{ marginTop: 26 }} />
            <div style={{ paddingTop: 16 }}>
              <Rubric en="How sure are we">{t("howSure", lang)}</Rubric>
              {/* Confidence per lead, said plainly, including the leads where we are weak. */}
              {LEADS.map((k, i) => {
                const bss = d.skill.bss[k];
                const w = skillWord(bss);
                const kt = karteFor(d.meta?.lead_dates?.[k]?.start ?? "");
                const usable = i < horizon;
                return (
                  <div key={k} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 0", borderBottom: "1px solid var(--rule)" }}>
                    <div style={{ width: 74, flexShrink: 0 }}>
                      <div className="kn" style={{ fontSize: 15, fontWeight: 700 }}>{kt ? kt[lang] ?? kt.en : `W${i + 1}`}</div>
                      <div className="cap" style={{ fontSize: 10 }}>week {i + 1}</div>
                    </div>
                    <div style={{ flex: 1, height: 7, background: "var(--paper3)", position: "relative" }}>
                      <div style={{ position: "absolute", inset: 0, width: `${Math.max(2, Math.min(100, bss * 400))}%`,
                        background: usable ? "var(--ok)" : "var(--rule2)" }} />
                    </div>
                    <div style={{ width: 118, flexShrink: 0, textAlign: "right" }}>
                      <div className="kn" style={{ fontSize: 13.5, fontWeight: 700, color: usable ? "var(--ink)" : "var(--ink3)" }}>
                        {w[lang] ?? w.en}
                      </div>
                    </div>
                  </div>
                );
              })}
              <div className="body-kn" style={{ marginTop: 14, color: "var(--ink2)", fontSize: 15.5 }}>
                {tpl("outlookNote", lang, horizon)}
              </div>
            </div>

            <hr className="hr-heavy" style={{ marginTop: 22 }} />
            <div style={{ paddingTop: 16 }}>
              <Rubric en="Where this comes from">{t("whereFrom", lang)}</Rubric>
              <ol className="ed" style={{ margin: 0, paddingLeft: 20, fontSize: 14.5, lineHeight: 1.65, color: "var(--ink2)" }}>
                <li>34 years of IMD rainfall for this hobli, 1991&ndash;2024 &mdash; of which
                  <b style={{ color: "var(--ink)" }} className="num"> {seasons ?? "—"}</b> are the seasons
                  scored above, the ones after training stopped.</li>
                {members ? (
                  <li><b style={{ color: "var(--ink)" }} className="num">{members}</b> ECMWF ensemble runs for the coming four weeks.</li>
                ) : null}
                <li>Rain gauges at every gram panchayat in Karnataka (KSNDMC), checked daily.</li>
                <li>ICAR&ndash;CRIDA district agriculture contingency plan for the crop advice.</li>
              </ol>
              <div className="gloss" style={{ marginTop: 12 }}>
                Trained on 1991&ndash;2015, tuned on 2016&ndash;2019, scored only on
                2020&ndash;2024 &mdash; a chronological split.
              </div>
            </div>
          </div>
        </div>
      </div>
      <Tabs lang={lang} />
    </Shell>
  );
}
