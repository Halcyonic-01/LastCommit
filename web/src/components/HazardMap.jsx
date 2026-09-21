import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

// Two ramps, two meanings. Water hazards run blue; dry hazards run amber to red.
// There is no single "good to bad" rainbow, because rain is not a severity.
// Ramp step 0 is deliberately the map's OWN background color, not a hue — low risk
// recedes into the panel rather than being "a colour", so only real risk pops. All
// three no-signal spots (the ramp, the pre-data placeholder, and "no data at all")
// share this one constant so a future theme change can't desync them again.
export const BASE  = "#ece5d6";
export const DRY   = [BASE, "#6b5526", "#a8761a", "#c05a2c", "#9a2a18"];
export const WATER = [BASE, "#20486a", "#12527f", "#2f79ad", "#5aa3dc"];

/** Karnataka block map, painted by whatever `values` says for the current frame.
 *
 * Shared by Officer (today's live forecast) and Replay (a hindcast day) — same
 * geometry, same paint mechanism, so the two screens can't quietly drift apart.
 * `values`: {area_id: number|null}. Repaints via feature-state on every change,
 * never rebuilds the style — that's what makes fast scrubbing/playback affordable. */
const REPORT_COLOR = { none: "#8a8272", light: "#2f79ad", heavy: "#12527f" };
const EMPTY_POINTS = { type: "FeatureCollection", features: [] };

export default function HazardMap({ values, ramp, onHover, style, points }) {
  const el = useRef(null);
  const map = useRef(null);
  // The values-effect needs the feature list to set per-feature state. Reading it back
  // via the source's `_data` is a private MapLibre internal that isn't even populated
  // until some other interaction has warmed the source up (confirmed against the
  // installed 4.7.1: GeoJSONSource keeps `_dataUpdateable`, not `_data`) — so the very
  // first paint silently no-opped and the map sat at the base colour until a click. Kept
  // here instead, from the same fetch this component already does.
  const features = useRef(null);
  // What the two data-effects below most recently wanted to paint, replayed once the
  // "load" handler finishes — see the note above `pendingFill`/`pendingPoints` calls.
  const pendingFill = useRef(null);
  const pendingPoints = useRef(null);

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
      features.current = geo.features;
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
      // Farmer rain reports — a real ground-truth dot, not a hazard prediction, so it
      // gets its own halo+fill circle rather than sharing the choropleth's ramp.
      map.current.addSource("points", { type: "geojson", data: EMPTY_POINTS });
      map.current.addLayer({ id: "point-halo", type: "circle", source: "points",
        paint: { "circle-radius": 6, "circle-color": "#fbf8f1" } });
      map.current.addLayer({ id: "point-dot", type: "circle", source: "points",
        paint: { "circle-radius": 4, "circle-color": ["get", "color"] } });
      map.current.on("mousemove", "fill", (e) => {
        const f = e.features?.[0]; if (!f) return;
        map.current.getCanvas().style.cursor = "pointer";
        map.current.setFilter("hl", ["==", ["get", "__i"], f.properties.__i]);
        map.current.setFilter("hl-halo", ["==", ["get", "__i"], f.properties.__i]);
        onHover?.(f.properties);
      });
      map.current.on("mouseleave", "fill", () => {
        map.current.getCanvas().style.cursor = "";
        map.current.setFilter("hl", ["==", ["get", "__i"], -1]);
        map.current.setFilter("hl-halo", ["==", ["get", "__i"], -1]);
        onHover?.(null);
      });
      map.current.fitBounds([[73.9, 11.4], [78.8, 18.6]], { padding: 16, duration: 0 });
      // The values/points effects below can run before this async handler finishes
      // (MapLibre's "idle" fires as soon as the empty initial style settles, often
      // before this handler's own geo fetch resolves) — a one-shot `once("idle", ...)`
      // registered at that moment fires immediately against a not-yet-ready map and is
      // then gone. Replaying whatever they last asked for, now that sources genuinely
      // exist, is what actually guarantees the first paint instead of racing on timing.
      pendingFill.current?.();
      pendingPoints.current?.();
    });
    return () => { map.current?.remove(); map.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // repaint via feature-state + a step expression — never a style rebuild
  useEffect(() => {
    if (!values) return;
    const apply = () => {
      if (!map.current?.getSource("blocks") || !features.current) return;
      map.current.setPaintProperty("fill", "fill-color", [
        "case", ["==", ["feature-state", "p"], null], BASE,
        ["step", ["feature-state", "p"], ramp[0], 0.2, ramp[1], 0.4, ramp[2], 0.6, ramp[3], 0.8, ramp[4]],
      ]);
      for (const f of features.current) {
        const v = values[f.properties.area_id];
        map.current.setFeatureState({ source: "blocks", id: f.properties.__i },
          { p: v == null ? null : v });
      }
    };
    pendingFill.current = apply;
    apply();
  }, [values, ramp]);

  useEffect(() => {
    const apply = () => {
      const src = map.current?.getSource("points");
      if (!src) return;
      src.setData({
        type: "FeatureCollection",
        features: (points ?? []).map((p) => ({
          type: "Feature", geometry: { type: "Point", coordinates: [p.lon, p.lat] },
          properties: { color: REPORT_COLOR[p.level] ?? REPORT_COLOR.none },
        })),
      });
    };
    pendingPoints.current = apply;
    apply();
  }, [points]);

  return <div ref={el} style={{ height: "min(62vh, 620px)", minHeight: 360, ...style }} />;
}
