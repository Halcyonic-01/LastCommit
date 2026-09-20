import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Link } from "react-router-dom";
import { getLatest, LEADS, advisoryHorizon } from "../lib/api.js";
import { karteFor } from "../i18n/strings.js";

// Two ramps, two meanings. Water hazards run blue; dry hazards run amber to red.
// There is no single "good to bad" rainbow, because rain is not a severity.
// Ramp step 0 is deliberately the map's OWN background color, not a hue — low risk
// recedes into the panel rather than being "a colour", so only real risk pops. All
// three no-signal spots (the ramp, the pre-data placeholder, and "no data at all")
// share this one constant so a future theme change can't desync them again.
const BASE  = "#ece5d6";
const DRY   = [BASE, "#6b5526", "#a8761a", "#c05a2c", "#9a2a18"];
const WATER = [BASE, "#20486a", "#12527f", "#2f79ad", "#5aa3dc"];
const HAZARDS = [
  { key: "p_dry7",        label: "Dry spell 7d",  ramp: DRY,   note: "7 consecutive days under 2.5 mm" },
  { key: "p_dry14",       label: "Dry spell 14d", ramp: DRY,   note: "14 consecutive dry days" },
  { key: "p_false_onset", label: "False onset",   ramp: DRY,   note: "rain starts, then stops for a week" },
  { key: "p_onset",       label: "Onset",         ramp: WATER, note: "monsoon onset in this window" },
  { key: "p_heavy",       label: "Heavy rain",    ramp: WATER, note: "daily total above the 95th percentile" },
];

export default function Officer() {
  const el = useRef(null);
  const map = useRef(null);
  const [latest, setLatest] = useState(null);
  const [hazard, setHazard] = useState("p_dry7");
  const [lead, setLead] = useState(0);
  const [hover, setHover] = useState(null);
  const [err, setErr] = useState(null);
  const [queued, setQueued] = useState([]);

  const H = HAZARDS.find((h) => h.key === hazard);

  useEffect(() => { getLatest().then(setLatest).catch((e) => setErr(e.message)); }, []);

  useEffect(() => {
    if (!el.current || map.current) return;
    map.current = new maplibregl.Map({
      container: el.current,
      // No tile provider — the polygons are the map. Offline-capable and free.
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": BASE } }] },
      center: [76.6, 15.0], zoom: 5.5, attributionControl: false,
    });
    map.current.on("load", async () => {
      const geo = await fetch("/geo/blocks.geojson").then((r) => r.json());
      geo.features.forEach((f, i) => { f.id = i; f.properties.__i = i; });
      map.current.addSource("blocks", { type: "geojson", data: geo, promoteId: "__i" });
      map.current.addLayer({ id: "fill", type: "fill", source: "blocks", paint: { "fill-color": BASE, "fill-opacity": 0.95 } });
      map.current.addLayer({ id: "line", type: "line", source: "blocks", paint: { "line-color": "#14171a", "line-width": 0.6 } });
      // A single-color highlight can't stay visible against every ramp step (a light
      // hover line disappears over the now-light BASE, a dark one disappears over the
      // dark end of a ramp) — a dark casing under a light line reads over anything.
      map.current.addLayer({ id: "hl-halo", type: "line", source: "blocks",
        paint: { "line-color": "#17140f", "line-width": 4 }, filter: ["==", ["get", "__i"], -1] });
      map.current.addLayer({ id: "hl", type: "line", source: "blocks",
        paint: { "line-color": "#fbf8f1", "line-width": 2 }, filter: ["==", ["get", "__i"], -1] });
      map.current.on("mousemove", "fill", (e) => {
        const f = e.features?.[0]; if (!f) return;
        map.current.getCanvas().style.cursor = "pointer";
        map.current.setFilter("hl", ["==", ["get", "__i"], f.properties.__i]);
        map.current.setFilter("hl-halo", ["==", ["get", "__i"], f.properties.__i]);
        setHover(f.properties);
      });
      map.current.on("mouseleave", "fill", () => {
        map.current.getCanvas().style.cursor = "";
        map.current.setFilter("hl", ["==", ["get", "__i"], -1]);
        map.current.setFilter("hl-halo", ["==", ["get", "__i"], -1]);
        setHover(null);
      });
      map.current.fitBounds([[73.9, 11.4], [78.8, 18.6]], { padding: 16, duration: 0 });
    });
    return () => { map.current?.remove(); map.current = null; };
  }, []);

  // repaint via feature-state + a step expression — never a style rebuild
  useEffect(() => {
    if (!map.current || !latest) return;
    const apply = () => {
      const src = map.current.getSource("blocks");
      if (!src?._data) return;
      map.current.setPaintProperty("fill", "fill-color", [
        "case", ["==", ["feature-state", "p"], null], BASE,
        ["step", ["feature-state", "p"], H.ramp[0], 0.2, H.ramp[1], 0.4, H.ramp[2], 0.6, H.ramp[3], 0.8, H.ramp[4]],
      ]);
      for (const f of src._data.features) {
        const a = latest.areas[f.properties.area_id];
        map.current.setFeatureState({ source: "blocks", id: f.properties.__i }, { p: a ? a[hazard][LEADS[lead]] : null });
      }
    };
    if (map.current.isStyleLoaded() && map.current.getSource("blocks")) apply();
    else map.current.once("idle", apply);
  }, [latest, hazard, lead, H]);

  const rows = latest
    ? Object.values(latest.areas).filter((a) => a.level === "block")
        .sort((a, b) => b[hazard][LEADS[lead]] - a[hazard][LEADS[lead]]).slice(0, 12)
    : [];
  const dates = latest?.meta?.lead_dates?.[LEADS[lead]];
  const karte = karteFor(dates?.start ?? "");
  const horizon = latest ? advisoryHorizon(latest.skill) : 2;
  const beyond = lead >= horizon;
  const toggle = (id) => setQueued((q) => (q.includes(id) ? q.filter((x) => x !== id) : [...q, id]));

  return (
    <div className="ops">
      <header style={{ background: "var(--paper3)", borderBottom: "1px solid var(--rule2)", padding: "13px 20px", display: "flex",
        alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="kn" style={{ fontSize: 21, fontWeight: 800, lineHeight: 1, color: "var(--ink)" }}>
            ವರ್ಷದೃಷ್ಟಿ <span className="ops-mono" style={{ fontSize: 11, fontWeight: 400, color: "var(--ink3)", letterSpacing: ".1em" }}>OPERATIONS</span>
          </div>
          <div className="ops-mono" style={{ fontSize: 11, color: "var(--ink2)", marginTop: 4 }}>
            KARNATAKA · {latest ? Object.keys(latest.areas).length : "—"} AREAS · RUN {latest?.provenance?.nwp?.run_date ?? "—"} · {latest?.meta?.model_version ?? ""}
          </div>
        </div>
        <Link to="/verify" className="ops-mono" style={{ fontSize: 12, color: "var(--ink)", borderBottom: "1px solid var(--rule2)", paddingBottom: 2 }}>
          FORECAST VERIFICATION →
        </Link>
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
          <div ref={el} style={{ height: "min(62vh, 620px)", minHeight: 360 }} />
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
              <div className="kn" style={{ fontSize: 15, fontWeight: 700 }}>{hover.name_kn || hover.name_en}</div>
              <div className="ops-mono" style={{ fontSize: 10.5, color: "var(--ink3)" }}>{hover.name_en} · {hover.district_en}</div>
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
                      <td style={{ padding: "6px 10px", borderBottom: "1px solid var(--rule)" }}>
                        <span className="kn" style={{ fontWeight: 700 }}>{a.name_kn || a.name_en}</span>
                        <span className="ops-mono" style={{ color: "var(--ink3)", fontSize: 10.5 }}> {a.name_en}</span>
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
        <button type="button" disabled={!queued.length || beyond}
          style={{ padding: "11px 20px", fontSize: 13, fontWeight: 700, background: queued.length && !beyond ? "var(--water2)" : "var(--paper3)",
            color: queued.length && !beyond ? "var(--paper2)" : "var(--ink3)", border: "none" }}>
          Review broadcast →
        </button>
        <div className="ops-mono" style={{ fontSize: 10.5, color: "var(--ink3)" }}>
          {beyond ? "blocked past the advisory horizon" : "opens a preview in Kannada before anything is sent"}
        </div>
      </div>

      {err ? <div style={{ padding: 16, color: "var(--risk)" }}>Could not load forecast: {err}</div> : null}
      <style>{`@media (min-width: 1040px){ .ops-grid { grid-template-columns: minmax(0,1.25fr) minmax(0,1fr) !important; } }`}</style>
    </div>
  );
}
