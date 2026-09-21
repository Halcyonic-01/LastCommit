import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { getLatest, LEADS, advisoryHorizon } from "../lib/api.js";
import { karteFor } from "../i18n/strings.js";
import HazardMap, { DRY, WATER } from "../components/HazardMap.jsx";
import BroadcastPanel from "../components/BroadcastPanel.jsx";

const HAZARDS = [
  { key: "p_dry7",        label: "Dry spell 7d",  ramp: DRY,   note: "7 consecutive days under 2.5 mm" },
  { key: "p_dry14",       label: "Dry spell 14d", ramp: DRY,   note: "14 consecutive dry days" },
  { key: "p_false_onset", label: "False onset",   ramp: DRY,   note: "sowing rain, then a 10-day near-dry spell within 30 days" },
  { key: "p_onset",       label: "Onset",         ramp: WATER, note: "monsoon onset in this window" },
  { key: "p_heavy",       label: "Heavy rain",    ramp: WATER, note: "daily total ≥ 64.5 mm, IMD's heavy-rain day" },
];

export default function Officer() {
  const [latest, setLatest] = useState(null);
  const [hazard, setHazard] = useState("p_dry7");
  const [lead, setLead] = useState(0);
  const [hover, setHover] = useState(null);
  const [err, setErr] = useState(null);
  const [queued, setQueued] = useState([]);
  const [reviewing, setReviewing] = useState(false);

  const H = HAZARDS.find((h) => h.key === hazard);

  useEffect(() => { getLatest().then(setLatest).catch((e) => setErr(e.message)); }, []);

  const values = {};
  if (latest) {
    for (const [aid, a] of Object.entries(latest.areas)) values[aid] = a[hazard]?.[LEADS[lead]] ?? null;
  }

  const rows = latest
    ? Object.values(latest.areas).filter((a) => a.level === "block")
        .sort((a, b) => b[hazard][LEADS[lead]] - a[hazard][LEADS[lead]]).slice(0, 12)
    : [];
  const dates = latest?.meta?.lead_dates?.[LEADS[lead]];
  const karte = karteFor(dates?.start ?? "");
  const horizon = latest ? advisoryHorizon(latest.skill) : 0;
  const beyond = lead >= horizon;
  const toggle = (id) => setQueued((q) => (q.includes(id) ? q.filter((x) => x !== id) : [...q, id]));

  return (
    <div className="ops">
      <header style={{ background: "var(--paper3)", borderBottom: "1px solid var(--rule2)", padding: "13px 20px", display: "flex",
        alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          {/* Officer tools are English-only by design — language here is a job requirement,
              not a preference, and never follows the farmer's own language choice. */}
          <div style={{ fontSize: 21, fontWeight: 800, lineHeight: 1, color: "var(--ink)" }}>
            VarshaDrishti <span className="ops-mono" style={{ fontSize: 11, fontWeight: 400, color: "var(--ink3)", letterSpacing: ".1em" }}>OPERATIONS</span>
          </div>
          <div className="ops-mono" style={{ fontSize: 11, color: "var(--ink2)", marginTop: 4 }}>
            KARNATAKA · {latest ? Object.keys(latest.areas).length : "—"} AREAS · RUN {latest?.provenance?.nwp?.run_date ?? "—"} · {latest?.meta?.model_version ?? ""}
          </div>
        </div>
        <div style={{ display: "flex", gap: 18 }}>
          <Link to="/replay" className="ops-mono" style={{ fontSize: 12, color: "var(--ink)", borderBottom: "1px solid var(--rule2)", paddingBottom: 2 }}>
            REPLAY 2024 →
          </Link>
          <Link to="/verify" className="ops-mono" style={{ fontSize: 12, color: "var(--ink)", borderBottom: "1px solid var(--rule2)", paddingBottom: 2 }}>
            FORECAST VERIFICATION →
          </Link>
        </div>
      </header>

      {/* lead selector reads as a timeline, and visibly stops being advisable */}
      <div style={{ borderBottom: "1px solid var(--rule)", padding: "10px 20px", display: "flex", gap: 22, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 0, border: "1px solid var(--rule2)" }}>
          {LEADS.map((k, i) => (
            <button key={k} type="button" onClick={() => setLead(i)}
              className="ops-mono"
              style={{ padding: "7px 14px", fontSize: 11.5, letterSpacing: ".06em",
                background: lead === i ? "var(--ink)" : "transparent",
                color: lead === i ? "var(--paper)" : i >= horizon ? "var(--ink3)" : "var(--ink2)",
                borderRight: i < 3 ? "1px solid var(--rule2)" : "none" }}>
              W{i + 1}{i >= horizon ? " ·" : ""}
            </button>
          ))}
        </div>
        <div className="ops-mono" style={{ fontSize: 11.5, color: "var(--ink2)" }}>
          {dates ? `${dates.start} → ${dates.end}` : ""}
          {karte ? <span style={{ color: "var(--ink3)" }}> · {karte.en} karte</span> : null}
        </div>
        <div style={{ display: "flex", gap: 0, marginLeft: "auto", flexWrap: "wrap", border: "1px solid var(--rule2)" }}>
          {HAZARDS.map((h, i) => (
            <button key={h.key} type="button" onClick={() => setHazard(h.key)} className="ops-mono"
              style={{ padding: "7px 12px", fontSize: 11.5, background: hazard === h.key ? "var(--paper3)" : "transparent",
                color: hazard === h.key ? "var(--ink)" : "var(--ink3)", borderRight: i < HAZARDS.length - 1 ? "1px solid var(--rule2)" : "none" }}>
              {h.label}
            </button>
          ))}
        </div>
      </div>

      {beyond ? (
        <div className="ops-mono" style={{ background: "var(--wait)", color: "#1a1206", fontSize: 11.5, padding: "6px 20px", letterSpacing: ".04em" }}>
          BEYOND THE {horizon}-WEEK ADVISORY HORIZON — OUTLOOK ONLY. DO NOT BROADCAST AS ADVICE.
        </div>
      ) : null}

      <div className="ops-grid" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr)", gap: 0 }}>
        <div style={{ position: "relative", borderRight: "1px solid var(--rule)" }}>
          <HazardMap values={values} ramp={H.ramp} onHover={setHover} />
          <div style={{ position: "absolute", left: 16, bottom: 16, background: "rgba(20,23,26,.9)",
            border: "1px solid var(--rule2)", padding: "9px 11px" }}>
            <div className="ops-mono" style={{ fontSize: 10, color: "var(--ink3)", letterSpacing: ".1em" }}>{H.label.toUpperCase()}</div>
            <div style={{ display: "flex", marginTop: 6 }}>
              {H.ramp.map((c) => <span key={c} style={{ width: 30, height: 9, background: c, display: "block" }} />)}
            </div>
            <div className="ops-mono" style={{ display: "flex", justifyContent: "space-between", fontSize: 9.5, color: "var(--ink3)", marginTop: 3 }}>
              <span>0</span><span>10/10</span>
            </div>
            <div className="ops-mono" style={{ fontSize: 9.5, color: "var(--ink3)", marginTop: 5, maxWidth: 150 }}>{H.note}</div>
          </div>
          {hover ? (
            <div style={{ position: "absolute", right: 16, top: 16, background: "rgba(20,23,26,.94)", border: "1px solid var(--rule2)", padding: "9px 12px" }}>
              <div style={{ fontSize: 15, fontWeight: 700 }}>{hover.name_en}</div>
              <div className="ops-mono" style={{ fontSize: 10.5, color: "var(--ink3)" }}>{hover.district_en}</div>
            </div>
          ) : null}
        </div>

        <div style={{ minWidth: 0 }}>
          <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--rule)" }}>
            <div style={{ fontSize: 15, fontWeight: 700 }}>Taluks that need a message today</div>
            <div className="ops-mono" style={{ fontSize: 10.5, color: "var(--ink3)", marginTop: 2 }}>
              TOP 12 BY {H.label.toUpperCase()} · WEEK {lead + 1}
            </div>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  {["", "TALUK", "DISTRICT", "RISK", "", "CELLS"].map((h, i) => (
                    <th key={i} className="ops-mono" style={{ textAlign: i >= 4 ? "right" : "left", padding: "7px 10px",
                      fontSize: 9.5, letterSpacing: ".1em", color: "var(--ink3)", borderBottom: "1px solid var(--rule2)", fontWeight: 400 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => {
                  const p = a[hazard][LEADS[lead]];
                  const on = queued.includes(a.area_id);
                  return (
                    <tr key={a.area_id} style={{ background: on ? "var(--paper3)" : "transparent" }}>
                      <td style={{ padding: "6px 10px", borderBottom: "1px solid var(--rule)" }}>
                        <input type="checkbox" checked={on} onChange={() => toggle(a.area_id)}
                          aria-label={`Queue ${a.name_en} for broadcast`} style={{ accentColor: "var(--water2)", width: 16, height: 16 }} />
                      </td>
                      <td style={{ padding: "6px 10px", borderBottom: "1px solid var(--rule)", fontWeight: 700 }}>
                        {a.name_en}
                      </td>
                      <td className="ops-mono" style={{ padding: "6px 10px", borderBottom: "1px solid var(--rule)", color: "var(--ink2)", fontSize: 11 }}>{a.district_en}</td>
                      <td style={{ padding: "6px 10px", borderBottom: "1px solid var(--rule)", minWidth: 96 }}>
                        <div style={{ height: 8, background: "var(--paper3)" }}>
                          <div style={{ width: `${Math.round(p * 100)}%`, height: "100%",
                            background: H.ramp[Math.min(4, Math.floor(p * 5))] }} />
                        </div>
                      </td>
                      <td className="ops-mono" style={{ padding: "6px 10px", borderBottom: "1px solid var(--rule)", textAlign: "right", fontWeight: 700 }}>
                        {Math.round(p * 100)}%
                      </td>
                      <td className="ops-mono" style={{ padding: "6px 10px", borderBottom: "1px solid var(--rule)", textAlign: "right", color: "var(--ink3)", fontSize: 11 }}>{a.n_cells}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* broadcast is an explicit, reviewable act — never a one-tap send */}
      <div style={{ borderTop: "1px solid var(--rule2)", padding: "12px 20px", display: "flex",
        alignItems: "center", gap: 16, flexWrap: "wrap", position: "sticky", bottom: 0, background: "var(--paper2)" }}>
        <div className="ops-mono" style={{ fontSize: 11.5, color: "var(--ink2)" }}>
          {queued.length} TALUK{queued.length === 1 ? "" : "S"} QUEUED
        </div>
        <button type="button" disabled={!queued.length || beyond} onClick={() => setReviewing(true)}
          style={{ padding: "11px 20px", fontSize: 13, fontWeight: 700, background: queued.length && !beyond ? "var(--water2)" : "var(--paper3)",
            color: queued.length && !beyond ? "var(--paper2)" : "var(--ink3)", border: "none" }}>
          Review broadcast →
        </button>
        <div className="ops-mono" style={{ fontSize: 10.5, color: "var(--ink3)" }}>
          {beyond ? "blocked past the advisory horizon" : "opens a preview in Kannada before anything is sent"}
        </div>
      </div>

      {reviewing ? (
        <BroadcastPanel
          areaIds={queued}
          areaNames={queued.map((id) => latest?.areas?.[id]?.name_en ?? id)}
          event={hazard}
          lead={LEADS[lead]}
          onClose={() => setReviewing(false)}
          onSent={() => { setQueued([]); setReviewing(false); }}
        />
      ) : null}

      {err ? <div style={{ padding: 16, color: "var(--risk)" }}>Could not load forecast: {err}</div> : null}
      <style>{`@media (min-width: 1040px){ .ops-grid { grid-template-columns: minmax(0,1.25fr) minmax(0,1fr) !important; } }`}</style>
    </div>
  );
}
