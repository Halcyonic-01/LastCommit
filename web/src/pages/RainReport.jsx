import { useState } from "react";
import { loadPrefs, queueReport, flushOutbox } from "../lib/store.js";
import { S, t, pick } from "../i18n/strings.js";
import Photo from "../components/Photo.jsx";
import Speak from "../components/Speak.jsx";
import Tabs from "../components/Tabs.jsx";
import { Shell } from "../components/Frame.jsx";
import { Tick } from "../components/Marks.jsx";

// Three answers, no typing, no scale, no form. Each one is a picture of itself.
const CHOICES = [
  { id: "none",  photo: "dry",     word: S.noRain },
  { id: "light", photo: "rain",    word: S.aLittle },
  { id: "heavy", photo: "monsoon", word: S.heavy },
];

export default function RainReport() {
  const { lang, areaId } = loadPrefs();
  const [picked, setPicked] = useState(null);
  const [sent, setSent] = useState(null);   // null | "stored" | "failed"

  // Save first, send second. The tap must never depend on a network that is not there.
  function submit() {
    const { stored } = queueReport({ areaId, level: picked });
    setSent(stored ? "stored" : "failed");
    if (stored) flushOutbox();
  }

  const ask = pick(S.didItRain, lang);

  if (sent) {
    const ok = sent === "stored";
    const head = ok ? S.thanks : S.notSaved;
    return (
      <Shell>
        <Photo name="ragi" lang={lang} className="-hero -tall">
          <div className="on-photo">
            <div className="kn" style={{ fontSize: 38, fontWeight: 800, lineHeight: 1.1 }}>{pick(head, lang)}</div>
            <div className="gloss gloss-on-photo" style={{ marginTop: 4 }}>{head.en}</div>
          </div>
        </Photo>
        <div className="grow pad colmax" style={{ paddingTop: 24 }}>
          {/* Where the report actually is, not a "sent" it cannot promise on 2G. */}
          <div className={ok ? "notice -ok" : "notice -wait"}>
            <div className="body-kn">{pick(ok ? S.savedHere : S.noSpace, lang)}</div>
            <div className="gloss" style={{ marginTop: 5 }}>{(ok ? S.savedHere : S.noSpace).en}</div>
            {ok ? (
              <>
                <div className="body-kn" style={{ marginTop: 10, color: "var(--ink2)" }}>{pick(S.willSend, lang)}</div>
                <div className="gloss" style={{ marginTop: 3 }}>{S.willSend.en}</div>
              </>
            ) : null}
          </div>
          {ok ? (
            <div style={{ marginTop: 18, display: "flex", gap: 9, alignItems: "flex-start" }}>
              <Tick size={17} />
              <div>
                <div className="body-kn" style={{ fontSize: 15 }}>{pick(S.reportHelps, lang)}</div>
                <div className="gloss">{S.reportHelps.en}</div>
              </div>
            </div>
          ) : null}
          <button type="button" className="btn -quiet" style={{ marginTop: 22 }}
            onClick={() => { setSent(null); setPicked(ok ? null : picked); }}>
            {t("again", lang)}
          </button>
        </div>
        <Tabs lang={lang} />
      </Shell>
    );
  }

  return (
    <Shell className="oneview">
      {/* The question is the entire header. Nothing competes with it. */}
      <div className="pad rule-b" style={{ paddingTop: 16, paddingBottom: 14, display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div className="kn" style={{ fontSize: 27, fontWeight: 800, lineHeight: 1.15 }}>{ask}</div>
          <div className="gloss" style={{ marginTop: 2 }}>{S.didItRain.en} Tap one.</div>
        </div>
        <Speak text={ask} lang={lang} variant="icon" />
      </div>

      {/* Three plates. Each fills a third of the screen — impossible to mis-tap
          with one hand, and readable without reading. */}
      <div className="grow" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {CHOICES.map((c) => {
          const on = picked === c.id;
          return (
            <button key={c.id} type="button" role="radio" aria-checked={on}
              onClick={() => setPicked(c.id)}
              className="plate"
              style={{ position: "relative",
                border: on ? "4px solid var(--ink)" : "none", borderBottom: on ? "4px solid var(--ink)" : "1px solid var(--rule2)" }}>
              <Photo name={c.photo} lang={lang} height="100%" credit={false} scrim={true} />
              {/* the word sits low, where the scrim is strongest — legible over a
                  bright cracked-earth frame as well as a dark storm one */}
              <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "flex-end",
                justifyContent: "space-between", padding: "0 20px 14px", color: "var(--ink-on-photo)" }}>
                <span style={{ textAlign: "left" }}>
                  <span className="kn" style={{ display: "block", fontSize: 32, fontWeight: 800, lineHeight: 1.1 }}>{pick(c.word, lang)}</span>
                  {lang !== "en" ? <span className="gloss gloss-on-photo">{c.word.en}</span> : null}
                </span>
                {on ? (
                  <span style={{ width: 44, height: 44, borderRadius: 22, background: "var(--ink-on-photo)", color: "var(--ink)",
                    display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                    <Tick size={24} />
                  </span>
                ) : null}
              </span>
            </button>
          );
        })}
      </div>

      <div className="pad" style={{ paddingTop: 14, paddingBottom: 14 }}>
        <button type="button" className="btn" disabled={!picked} onClick={submit}
          style={{ opacity: picked ? 1 : 0.35 }}>
          {t("send", lang)}
        </button>
        <div className="gloss" style={{ textAlign: "center", marginTop: 9 }}>{pick(S.reportHelps, lang)}</div>
      </div>
      <Tabs lang={lang} />
    </Shell>
  );
}
