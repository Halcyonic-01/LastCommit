import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getLatest, LEADS, skillWord, advisoryHorizon } from "../lib/api.js";

/** Reliability: forecast probability against what actually happened.
 *  Drawn only from `skill.reliability` in the contract. If the pipeline has not
 *  emitted bins yet we draw the empty frame and say so, rather than inventing a
 *  curve — this screen exists to be trusted. */
function Reliability({ bins }) {
  const S = 260, pad = 34, w = S - pad * 2;
  const xy = (p) => [pad + p * w, S - pad - p * w];
  return (
    <svg viewBox={`0 0 ${S} ${S}`} width="100%" style={{ maxWidth: 320 }} role="img"
      aria-label="Reliability diagram: forecast probability against observed frequency">
      <rect x={pad} y={pad} width={w} height={w} fill="#20262b" stroke="#3a434b" />
      {[0.25, 0.5, 0.75].map((g) => (
        <g key={g} stroke="#2b3238">
          <line x1={pad + g * w} y1={pad} x2={pad + g * w} y2={S - pad} />
          <line x1={pad} y1={S - pad - g * w} x2={S - pad} y2={S - pad - g * w} />
        </g>
      ))}
      {/* perfect reliability */}
      <line x1={pad} y1={S - pad} x2={S - pad} y2={pad} stroke="#6f7981" strokeDasharray="4 4" />
      {bins?.length ? (
        <polyline fill="none" stroke="#5aa3dc" strokeWidth="2.5"
          points={bins.map((b) => xy(b.forecast).map((n) => n.toFixed(1)).join(",")).join(" ")
            .replace(/,(\S+) /g, ",$1 ")} />
      ) : null}
      {bins?.map((b, i) => {
        const [x, y] = xy(b.forecast);
        return <circle key={i} cx={x} cy={S - pad - b.observed * w} r="3.5" fill="#5aa3dc" />;
      })}
      <text x={pad} y={S - 10} fill="#6f7981" fontSize="9" fontFamily="monospace">0</text>
      <text x={S - pad - 8} y={S - 10} fill="#6f7981" fontSize="9" fontFamily="monospace">1</text>
      <text x={S / 2 - 40} y={S - 10} fill="#6f7981" fontSize="9" fontFamily="monospace">FORECAST</text>
      <text x={8} y={pad + 8} fill="#6f7981" fontSize="9" fontFamily="monospace">1</text>
      <text x={8} y={S - pad} fill="#6f7981" fontSize="9" fontFamily="monospace">0</text>
    </svg>
  );
}

export default function Verify() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { getLatest().then(setD).catch((e) => setErr(e.message)); }, []);

  const skill = d?.skill;
  const bins = skill?.reliability?.bins;
  const horizon = advisoryHorizon(skill);

  return (
    <div className="ops">
      <header style={{ borderBottom: "1px solid var(--rule2)", padding: "13px 20px", display: "flex",
        justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 19, fontWeight: 700 }}>Forecast verification</div>
          <div className="ops-mono" style={{ fontSize: 11, color: "var(--ink2)", marginTop: 3 }}>
            {/* the reference string states its own protocol — hardcoding one here went
                stale the moment the backend changed */}
            {skill?.reference?.toUpperCase() ?? "SCORED AGAINST CLIMATOLOGY"}
          </div>
        </div>
        <Link to="/officer" className="ops-mono" style={{ fontSize: 12, borderBottom: "1px solid var(--rule2)", paddingBottom: 2 }}>← OPERATIONS</Link>
      </header>

      {err ? <div style={{ padding: 20, color: "var(--risk)" }}>Could not load: {err}</div> : null}

      <div style={{ display: "grid", gap: 0, gridTemplateColumns: "minmax(0,1fr)", maxWidth: 1180 }} className="ver-grid">
        {/* skill by lead — including the lead where we are worse than guessing */}
        <section style={{ padding: 20, borderRight: "1px solid var(--rule)" }}>
          <div className="ops-mono" style={{ fontSize: 10, letterSpacing: ".12em", color: "var(--ink3)" }}>BRIER SKILL SCORE BY LEAD</div>
          {/* Describe what the numbers ARE, never what they were assumed to be: this
              said "week 4 is negative" long after week 4 turned positive. */}
          <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 6, maxWidth: 480 }}>
            Right of the centre line means the forecast beat climatology. Every lead is
            shown, weak ones included — that is the point of this screen.
          </div>
          <div style={{ marginTop: 18 }}>
            {LEADS.map((k, i) => {
              const v = skill?.bss?.[k];
              if (v == null) return null;
              const neg = v < 0, mag = Math.min(1, Math.abs(v) / 0.3);
              const w = skillWord(v);
              return (
                <div key={k} style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 0", borderBottom: "1px solid var(--rule)" }}>
                  <div className="ops-mono" style={{ width: 62, fontSize: 11.5, color: i < horizon ? "var(--ink)" : "var(--ink3)" }}>
                    WEEK {i + 1}{i >= horizon ? " ·" : ""}
                  </div>
                  <div style={{ flex: 1, display: "flex", alignItems: "center", height: 16, minWidth: 140 }}>
                    <div style={{ flex: 1, display: "flex", justifyContent: "flex-end" }}>
                      {neg ? <div style={{ height: 14, width: `${mag * 100}%`, background: "var(--risk)" }} /> : null}
                    </div>
                    <div style={{ width: 2, height: 22, background: "var(--ink3)" }} title="climatology" />
                    <div style={{ flex: 1 }}>
                      {!neg ? <div style={{ height: 14, width: `${mag * 100}%`, background: "var(--ok)" }} /> : null}
                    </div>
                  </div>
                  <div className="ops-mono" style={{ width: 54, textAlign: "right", fontWeight: 700, color: neg ? "var(--risk)" : "var(--ok)" }}>
                    {v > 0 ? "+" : ""}{v.toFixed(2)}
                  </div>
                  <div style={{ width: 160, fontSize: 12.5, color: "var(--ink2)", textAlign: "right" }}>{w.en}</div>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 18, borderLeft: "3px solid var(--wait)", paddingLeft: 12, fontSize: 13, color: "var(--ink2)", maxWidth: 480 }}>
            The farmer app refuses to give an action past week {horizon}, the last lead whose
            95% interval clears zero. It shows the weeks beyond it
            as an outlook with a dashed baseline, and says "outlook only" out loud.
          </div>
        </section>

        <section style={{ padding: 20 }}>
          <div className="ops-mono" style={{ fontSize: 10, letterSpacing: ".12em", color: "var(--ink3)" }}>RELIABILITY · WEEK 1</div>
          <div style={{ marginTop: 12 }}><Reliability bins={bins} /></div>
          {bins?.length ? (
            <div style={{ fontSize: 12.5, color: "var(--ink2)", marginTop: 8, maxWidth: 320 }}>
              On the dashed line means that when we said 30%, it happened 3 times in 10.
              Below the line is over-forecasting.
            </div>
          ) : (
            <div style={{ borderLeft: "3px solid var(--rule2)", paddingLeft: 12, marginTop: 8, maxWidth: 340 }}>
              <div className="ops-mono" style={{ fontSize: 10.5, color: "var(--wait)", letterSpacing: ".08em" }}>NOT YET COMPUTED</div>
              <div style={{ fontSize: 12.5, color: "var(--ink2)", marginTop: 5 }}>
                The contract has no <span className="ops-mono">skill.reliability.bins</span> yet, so nothing is
                plotted. The frame and the perfect-reliability diagonal are drawn so the shape of the
                missing evidence is visible. Emit bins of
                <span className="ops-mono"> {"{forecast, observed, n}"}</span> and this fills itself in.
              </div>
            </div>
          )}

          <div style={{ marginTop: 26, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: 1, background: "var(--rule)" }}>
            {[
              [skill?.roc_auc?.toFixed(2) ?? "—", "week-1 ROC-AUC for dry spells. Good, not magic."],
              // seasons SCORED, never seasons trained — the evidence is the held-out set
              [skill?.seasons_scored ? String(skill.seasons_scored) : "—", "independent seasons these numbers were measured on."],
              [d?.provenance?.nwp?.members ?? "—", "ensemble members blended in, weighted most heavily at week 1."],
            ].map(([n, txt]) => (
              <div key={txt} style={{ background: "var(--paper2)", padding: "12px 14px" }}>
                <div className="ops-mono" style={{ fontSize: 24, fontWeight: 700, lineHeight: 1 }}>{n}</div>
                <div style={{ fontSize: 11.5, color: "var(--ink3)", marginTop: 5, lineHeight: 1.45 }}>{txt}</div>
              </div>
            ))}
          </div>

          {d?.meta?.is_mock ? (
            <div className="ops-mono" style={{ marginTop: 20, background: "var(--wait)", color: "#1a1206",
              fontSize: 11, padding: "7px 11px", letterSpacing: ".04em" }}>
              MOCK FORECAST · {d.meta.model_version} · NOT FIT FOR FIELD USE
            </div>
          ) : null}
        </section>
      </div>
      <style>{`@media (min-width: 1040px){ .ver-grid { grid-template-columns: minmax(0,1.2fr) minmax(0,1fr) !important; } }`}</style>
    </div>
  );
}
