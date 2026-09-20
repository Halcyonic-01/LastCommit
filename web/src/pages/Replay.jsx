import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getLatest } from "../lib/api.js";

const EVENTS = [
  { key: "onset", label: "Onset" },
  { key: "false_onset", label: "False onset" },
  { key: "dry7", label: "Dry spell 7d" },
  { key: "dry14", label: "Dry spell 14d" },
  { key: "heavy", label: "Heavy rain" },
];

/** One event: predicted probability beside what the same real IMD data says happened. */
function Bar({ label, pred, actual }) {
  const hit = actual >= 0.5;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0" }}>
      <div style={{ width: 92, fontSize: 12, color: "var(--ink2)" }}>{label}</div>
      <div style={{ flex: 1, background: "var(--rule)", height: 14, position: "relative" }}>
        <div style={{ width: `${pred * 100}%`, height: "100%", background: "var(--water2)" }} />
      </div>
      <div className="ops-mono" style={{ width: 40, fontSize: 11.5, textAlign: "right" }}>{Math.round(pred * 100)}%</div>
      <div className="ops-mono" style={{ width: 66, fontSize: 10.5, textAlign: "right",
        color: hit ? "var(--risk)" : "var(--ok)" }}>
        {hit ? "HAPPENED" : "did not"}
      </div>
    </div>
  );
}

/** Daily rain, plain bars — the ground truth the spotlight's claim rests on. */
function RainStrip({ rain }) {
  const days = Object.entries(rain);
  const max = Math.max(...days.map(([, v]) => v), 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 60, marginTop: 10 }}>
      {days.map(([d, v]) => (
        <div key={d} title={`${d}: ${v} mm`} style={{ flex: 1, height: `${(v / max) * 100}%`,
          minHeight: v > 0 ? 2 : 1, background: v > 0 ? "var(--water2)" : "var(--rule2)" }} />
      ))}
    </div>
  );
}

function Spotlight({ s }) {
  if (!s) return null;
  return (
    <section style={{ padding: 20, borderBottom: "1px solid var(--rule)" }}>
      <div className="ops-mono" style={{ fontSize: 10, letterSpacing: ".12em", color: "var(--ink3)" }}>
        A REAL CALL, CHECKED AGAINST WHAT ACTUALLY HAPPENED
      </div>
      <div style={{ fontSize: 17, fontWeight: 700, marginTop: 6 }}>
        {s.name_en}, {s.district_en} · {s.forecast_date}
      </div>
      <p style={{ fontSize: 13.5, color: "var(--ink2)", marginTop: 8, maxWidth: 620, lineHeight: 1.55 }}>
        {s.narrative_en}
      </p>
      <div style={{ marginTop: 14, maxWidth: 420 }}>
        {EVENTS.map((e) => s.forecast[e.key]
          ? <Bar key={e.key} label={e.label} pred={s.forecast[e.key].pred} actual={s.forecast[e.key].actual} />
          : null)}
      </div>
      <div className="ops-mono" style={{ fontSize: 10, color: "var(--ink3)", marginTop: 16 }}>
        DAILY RAINFALL, 13–31 AUG 2024 (REAL IMD DATA)
      </div>
      <RainStrip rain={s.rain_mm} />
    </section>
  );
}

export default function Replay() {
  const [spotlight, setSpotlight] = useState(null);
  const [hindcast, setHindcast] = useState(null);
  const [latest, setLatest] = useState(null);
  const [err, setErr] = useState(null);
  const [areaId, setAreaId] = useState(null);
  const [date, setDate] = useState(null);

  useEffect(() => {
    Promise.all([
      fetch("/forecast/hindcast/spotlight.json").then((r) => r.json()),
      fetch("/forecast/hindcast/2024.json").then((r) => r.json()),
      getLatest(),
    ]).then(([sp, hc, lt]) => {
      setSpotlight(sp); setHindcast(hc); setLatest(lt);
      const first = Object.keys(hc.areas)[0];
      setAreaId(first);
      setDate(Object.keys(hc.areas[first])[0]);
    }).catch((e) => setErr(e.message));
  }, []);

  const districts = useMemo(() => {
    if (!hindcast || !latest) return [];
    return Object.keys(hindcast.areas)
      .map((id) => ({ id, name: latest.areas[id]?.name_en || id }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [hindcast, latest]);

  const dates = areaId && hindcast ? Object.keys(hindcast.areas[areaId]).sort() : [];
  const day = areaId && date ? hindcast?.areas[areaId]?.[date] : null;

  return (
    <div className="ops">
      <header style={{ borderBottom: "1px solid var(--rule2)", padding: "13px 20px", display: "flex",
        justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 19, fontWeight: 700 }}>Replay — Jun–Aug 2024</div>
          <div className="ops-mono" style={{ fontSize: 11, color: "var(--ink2)", marginTop: 3 }}>
            THE SHIPPED MODEL, RUN ON A SEASON IT NEVER TRAINED ON · SAME EVIDENCE AS /VERIFY
          </div>
        </div>
        <Link to="/verify" className="ops-mono" style={{ fontSize: 12, color: "var(--ink)", borderBottom: "1px solid var(--rule2)", paddingBottom: 2 }}>
          FORECAST VERIFICATION →
        </Link>
      </header>

      {err ? <div style={{ padding: 20, color: "var(--risk)" }}>Could not load: {err}</div> : null}

      <Spotlight s={spotlight} />

      <section style={{ padding: 20 }}>
        <div className="ops-mono" style={{ fontSize: 10, letterSpacing: ".12em", color: "var(--ink3)" }}>
          PICK ANY DISTRICT AND DAY
        </div>
        <div style={{ display: "flex", gap: 12, marginTop: 10, flexWrap: "wrap" }}>
          <select value={areaId ?? ""} onChange={(e) => setAreaId(e.target.value)}
            style={{ padding: "6px 10px", fontSize: 13, background: "var(--paper2)", border: "1px solid var(--rule2)" }}>
            {districts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <input type="range" min={0} max={Math.max(0, dates.length - 1)}
            value={Math.max(0, dates.indexOf(date))}
            onChange={(e) => setDate(dates[Number(e.target.value)])}
            style={{ flex: 1, minWidth: 200 }} />
          <div className="ops-mono" style={{ fontSize: 13, width: 92 }}>{date}</div>
        </div>
        <div style={{ marginTop: 16, maxWidth: 420 }}>
          {day ? EVENTS.map((e) => day[`${e.key}_w1`]
            ? <Bar key={e.key} label={e.label} pred={day[`${e.key}_w1`].pred} actual={day[`${e.key}_w1`].actual} />
            : null) : <div style={{ color: "var(--ink3)", fontSize: 13 }}>Loading…</div>}
        </div>
        <div style={{ fontSize: 11.5, color: "var(--ink3)", marginTop: 14, maxWidth: 480 }}>
          Week-1 probability at district level, aggregated the same way every published
          forecast is. "HAPPENED"/"did not" is the real y_* label for that date, from the
          same IMD archive the model was scored against in models/metrics.json — not a
          simulation.
        </div>
      </section>
    </div>
  );
}
