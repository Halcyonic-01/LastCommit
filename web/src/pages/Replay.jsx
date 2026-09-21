import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import HazardMap, { DRY, WATER } from "../components/HazardMap.jsx";
import { getLatest } from "../lib/api.js";

const HAZARDS = [
  { key: "onset",       label: "Onset",         ramp: WATER },
  { key: "false_onset", label: "False onset",   ramp: DRY },
  { key: "dry7",        label: "Dry spell 7d",  ramp: DRY },
  { key: "dry14",       label: "Dry spell 14d", ramp: DRY },
  { key: "heavy",       label: "Heavy rain",    ramp: WATER },
];
const LEADS = ["w1", "w2", "w3", "w4"];
const PLAY_MS = 350;

/** Same daily-rainfall strip idea as before, kept small — the ground truth a claim rests on. */
function RainStrip({ rain }) {
  const days = Object.entries(rain);
  const max = Math.max(...days.map(([, v]) => v), 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 44, marginTop: 8 }}>
      {days.map(([d, v]) => (
        <div key={d} title={`${d}: ${v} mm`} style={{ flex: 1, height: `${(v / max) * 100}%`,
          minHeight: v > 0 ? 2 : 1, background: v > 0 ? "var(--water2)" : "var(--rule2)" }} />
      ))}
    </div>
  );
}

/** The story, leading — not one card among equals. */
function Spotlight({ s, onShow }) {
  if (!s) return null;
  return (
    <section style={{ padding: 20, borderBottom: "1px solid var(--rule2)", background: "var(--paper3)" }}>
      <div className="ops-mono" style={{ fontSize: 10, letterSpacing: ".12em", color: "var(--ink3)" }}>
        A REAL CALL, CHECKED AGAINST WHAT ACTUALLY HAPPENED
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
        <div style={{ fontSize: 19, fontWeight: 700, marginTop: 6 }}>
          {s.name_en}, {s.district_en} · {s.forecast_date}
        </div>
        <button type="button" onClick={onShow} className="ops-mono"
          style={{ padding: "8px 14px", fontSize: 11.5, fontWeight: 700, background: "var(--water2)",
            color: "var(--paper2)", border: "none", letterSpacing: ".04em" }}>
          SHOW ON THE MAP →
        </button>
      </div>
      <p style={{ fontSize: 13.5, color: "var(--ink2)", marginTop: 8, maxWidth: 680, lineHeight: 1.55 }}>
        {s.narrative_en}
      </p>
      <div style={{ display: "flex", gap: 24, marginTop: 10, flexWrap: "wrap" }}>
        {["onset", "false_onset"].map((k) => (
          <div key={k} className="ops-mono" style={{ fontSize: 12 }}>
            {k === "onset" ? "ONSET" : "FALSE ONSET"} <b>{Math.round(s.forecast[k].pred * 100)}%</b>
            <span style={{ color: "var(--risk)", marginLeft: 6 }}>HAPPENED</span>
          </div>
        ))}
      </div>
      <div className="ops-mono" style={{ fontSize: 9.5, color: "var(--ink3)", marginTop: 12 }}>
        DAILY RAINFALL, 13–31 AUG 2024 (REAL IMD DATA)
      </div>
      <RainStrip rain={s.rain_mm} />
    </section>
  );
}

export default function Replay() {
  const [manifest, setManifest] = useState(null);
  const [spotlight, setSpotlight] = useState(null);
  const [latest, setLatest] = useState(null);
  const [err, setErr] = useState(null);

  const [hazard, setHazard] = useState("false_onset");
  const [lead, setLead] = useState(0);
  const [kind, setKind] = useState("pred"); // "pred" | "actual"
  const [dateIdx, setDateIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [hover, setHover] = useState(null);

  const cache = useRef({}); // "{hazard}_{lead}" -> {dates, frames}
  const [frameData, setFrameData] = useState(null);

  useEffect(() => {
    Promise.all([
      fetch("/forecast/hindcast/manifest.json").then((r) => r.json()),
      fetch("/forecast/hindcast/spotlight.json").then((r) => r.json()),
      getLatest(),
    ]).then(([m, sp, lt]) => { setManifest(m); setSpotlight(sp); setLatest(lt); })
      .catch((e) => setErr(e.message));
  }, []);

  const fileKey = `${hazard}_${LEADS[lead]}`;
  useEffect(() => {
    if (!manifest) return;
    if (cache.current[fileKey]) { setFrameData(cache.current[fileKey]); return; }
    fetch(`/forecast/hindcast/frames/${fileKey}.json`).then((r) => r.json()).then((d) => {
      cache.current[fileKey] = d;
      setFrameData(d);
    }).catch((e) => setErr(e.message));
  }, [fileKey, manifest]);

  // playback: advance one day at a time while `playing`, loop at the end
  useEffect(() => {
    if (!playing || !frameData) return;
    const id = setInterval(() => {
      setDateIdx((i) => (i + 1) % frameData.dates.length);
    }, PLAY_MS);
    return () => clearInterval(id);
  }, [playing, frameData]);

  const H = HAZARDS.find((h) => h.key === hazard);
  const date = frameData?.dates[dateIdx];
  const values = {};
  if (frameData && date) {
    const day = frameData.frames[date] || {};
    for (const [aid, [pred, actual]] of Object.entries(day)) values[aid] = kind === "pred" ? pred : actual;
  }

  function showSpotlight() {
    if (!spotlight || !frameData) return;
    setHazard("false_onset"); setLead(0); setKind("pred");
    const idx = frameData.dates.indexOf(spotlight.forecast_date);
    if (idx >= 0) setDateIdx(idx);
    setPlaying(false);
  }

  return (
    <div className="ops">
      <header style={{ background: "var(--paper3)", borderBottom: "1px solid var(--rule2)", padding: "13px 20px", display: "flex",
        justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="kn" style={{ fontSize: 21, fontWeight: 800, lineHeight: 1, color: "var(--ink)" }}>
            REPLAY <span className="ops-mono" style={{ fontSize: 11, fontWeight: 400, color: "var(--ink3)", letterSpacing: ".1em" }}>JUN–AUG 2024</span>
          </div>
          <div className="ops-mono" style={{ fontSize: 11, color: "var(--ink2)", marginTop: 4 }}>
            THE SHIPPED MODEL, RUN ON A SEASON IT NEVER TRAINED ON · SAME EVIDENCE AS /VERIFY
          </div>
        </div>
        <div style={{ display: "flex", gap: 18 }}>
          <Link to="/officer" className="ops-mono" style={{ fontSize: 12, color: "var(--ink)", borderBottom: "1px solid var(--rule2)", paddingBottom: 2 }}>← OPERATIONS</Link>
          <Link to="/verify" className="ops-mono" style={{ fontSize: 12, color: "var(--ink)", borderBottom: "1px solid var(--rule2)", paddingBottom: 2 }}>FORECAST VERIFICATION →</Link>
        </div>
      </header>

      {err ? <div style={{ padding: 20, color: "var(--risk)" }}>Could not load: {err}</div> : null}

      <Spotlight s={spotlight} onShow={showSpotlight} />

      {/* hazard + lead + predicted/actual — same control language as /officer */}
      <div style={{ borderBottom: "1px solid var(--rule)", padding: "10px 20px", display: "flex", gap: 22, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ display: "flex", border: "1px solid var(--rule2)" }}>
          {LEADS.map((k, i) => (
            <button key={k} type="button" onClick={() => setLead(i)} className="ops-mono"
              style={{ padding: "7px 14px", fontSize: 11.5, letterSpacing: ".06em",
                background: lead === i ? "var(--ink)" : "transparent",
                color: lead === i ? "var(--paper)" : "var(--ink2)",
                borderRight: i < 3 ? "1px solid var(--rule2)" : "none" }}>
              W{i + 1}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", border: "1px solid var(--rule2)" }}>
          {["pred", "actual"].map((k) => (
            <button key={k} type="button" onClick={() => setKind(k)} className="ops-mono"
              style={{ padding: "7px 14px", fontSize: 11.5, letterSpacing: ".06em",
                background: kind === k ? "var(--water2)" : "transparent",
                color: kind === k ? "var(--paper2)" : "var(--ink2)" }}>
              {k === "pred" ? "WHAT WE SAID" : "WHAT HAPPENED"}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", marginLeft: "auto", flexWrap: "wrap", border: "1px solid var(--rule2)" }}>
          {HAZARDS.map((h, i) => (
            <button key={h.key} type="button" onClick={() => setHazard(h.key)} className="ops-mono"
              style={{ padding: "7px 12px", fontSize: 11.5, background: hazard === h.key ? "var(--paper3)" : "transparent",
                color: hazard === h.key ? "var(--ink)" : "var(--ink3)", borderRight: i < HAZARDS.length - 1 ? "1px solid var(--rule2)" : "none" }}>
              {h.label}
            </button>
          ))}
        </div>
      </div>

      {/* playback */}
      <div style={{ padding: "10px 20px", display: "flex", gap: 12, alignItems: "center", borderBottom: "1px solid var(--rule)" }}>
        <button type="button" onClick={() => setPlaying((p) => !p)} className="ops-mono"
          style={{ width: 34, height: 34, background: "var(--ink)", color: "var(--paper)", border: "none", fontSize: 14 }}
          aria-label={playing ? "Pause" : "Play"}>
          {playing ? "❚❚" : "▶"}
        </button>
        <input type="range" min={0} max={Math.max(0, (frameData?.dates.length ?? 1) - 1)} value={dateIdx}
          onChange={(e) => { setPlaying(false); setDateIdx(Number(e.target.value)); }}
          style={{ flex: 1, minWidth: 160 }} />
        <div className="ops-mono" style={{ fontSize: 13, width: 92, textAlign: "right" }}>{date ?? "…"}</div>
      </div>

      <div className="ops-grid" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr)", gap: 0 }}>
        <div style={{ position: "relative", borderRight: "1px solid var(--rule)" }}>
          <HazardMap values={values} ramp={H.ramp} onHover={setHover} />
          <div style={{ position: "absolute", left: 16, bottom: 16, background: "rgba(20,23,26,.9)",
            border: "1px solid var(--rule2)", padding: "9px 11px" }}>
            <div className="ops-mono" style={{ fontSize: 10, color: "var(--ink3)", letterSpacing: ".1em" }}>
              {H.label.toUpperCase()} · {kind === "pred" ? "PREDICTED" : "ACTUAL"}
            </div>
            <div style={{ display: "flex", marginTop: 6 }}>
              {H.ramp.map((c) => <span key={c} style={{ width: 30, height: 9, background: c, display: "block" }} />)}
            </div>
            <div className="ops-mono" style={{ display: "flex", justifyContent: "space-between", fontSize: 9.5, color: "var(--ink3)", marginTop: 3 }}>
              <span>0</span><span>10/10</span>
            </div>
          </div>
          {hover ? (
            <div style={{ position: "absolute", right: 16, top: 16, background: "rgba(20,23,26,.94)", border: "1px solid var(--rule2)", padding: "9px 12px" }}>
              <div style={{ fontSize: 15, fontWeight: 700 }}>{hover.name_en}</div>
              <div className="ops-mono" style={{ fontSize: 10.5, color: "var(--ink3)" }}>{hover.name_en} · {hover.district_en}</div>
              {latest?.areas[hover.area_id] ? (
                <div className="ops-mono" style={{ fontSize: 10, color: "var(--ink3)", marginTop: 4 }}>
                  live today: {Math.round((latest.areas[hover.area_id][`p_${hazard}`]?.w1 ?? 0) * 100)}%
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      <div style={{ padding: "12px 20px", fontSize: 11.5, color: "var(--ink3)", maxWidth: 620 }}>
        "WHAT WE SAID" is the shipped model's real week-{lead + 1} probability for that day, at
        block resolution, aggregated the same way every published forecast is. "WHAT HAPPENED"
        is the real y_* label from the same IMD archive the model was scored against in
        models/metrics.json — not a simulation. Flip between them on the same day to see
        whether the call held.
      </div>
      <style>{`@media (min-width: 1040px){ .ops-grid { grid-template-columns: minmax(0,1fr) !important; } }`}</style>
    </div>
  );
}
