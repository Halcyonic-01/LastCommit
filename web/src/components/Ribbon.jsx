import { LEADS, outOfTen } from "../lib/api.js";
import { karteFor, t } from "../i18n/strings.js";

/** Four weeks left to right. Confidence is rendered, not labelled: the ink
 *  fades, the fill breaks into hatching and the baseline turns dashed once we
 *  are past the advisory horizon the contract allows us to advise on. */
export default function Ribbon({ forecast, meta, horizon, lang = "kn" }) {
  return (
    <div className="ribbon">
      {LEADS.map((k, i) => {
        const p = forecast.p_dry7[k];
        const out = i >= horizon;
        const kt = karteFor(meta?.lead_dates?.[k]?.start ?? "");
        const start = meta?.lead_dates?.[k]?.start;
        return (
          <div key={k} className={`wk${out ? " -outlook" : ""}`} style={{ opacity: 1 - i * 0.17 }}>
            <div className="rubric" style={{ fontSize: 9.5 }}>{i === 0 ? t("today", lang) : `+${i}`}</div>
            <div className="kn" style={{ fontSize: 15, fontWeight: 700, lineHeight: 1.2, marginTop: 1 }}>
              {kt ? kt[lang] ?? kt.en : `W${i + 1}`}
            </div>
            <div className="bar" style={{ marginTop: 6 }}>
              <span style={{ height: `${Math.max(6, p * 100)}%` }} />
            </div>
            <div className="base" />
            <div className="num" style={{ fontSize: 15, fontWeight: 700, marginTop: 5 }}>
              {outOfTen(p)}<span style={{ fontSize: 10.5, color: "var(--ink3)" }}>/10</span>
            </div>
            {start ? (
              <div className="cap" style={{ fontSize: 9.5, color: "var(--ink3)" }}>
                {new Date(start).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
