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
export default function HazardMap({ values, ramp, onHover, style }) {
  const el = useRef(null);
  const map = useRef(null);

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
        onHover?.(f.properties);
      });
      map.current.on("mouseleave", "fill", () => {
        map.current.getCanvas().style.cursor = "";
        map.current.setFilter("hl", ["==", ["get", "__i"], -1]);
        map.current.setFilter("hl-halo", ["==", ["get", "__i"], -1]);
        onHover?.(null);
      });
      map.current.fitBounds([[73.9, 11.4], [78.8, 18.6]], { padding: 16, duration: 0 });
    });
    return () => { map.current?.remove(); map.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // repaint via feature-state + a step expression — never a style rebuild
  useEffect(() => {
    if (!map.current || !values) return;
    const apply = () => {
      const src = map.current.getSource("blocks");
      if (!src?._data) return;
      map.current.setPaintProperty("fill", "fill-color", [
        "case", ["==", ["feature-state", "p"], null], BASE,
        ["step", ["feature-state", "p"], ramp[0], 0.2, ramp[1], 0.4, ramp[2], 0.6, ramp[3], 0.8, ramp[4]],
      ]);
      for (const f of src._data.features) {
        const v = values[f.properties.area_id];
        map.current.setFeatureState({ source: "blocks", id: f.properties.__i },
          { p: v == null ? null : v });
      }
    };
    if (map.current.isStyleLoaded() && map.current.getSource("blocks")) apply();
    else map.current.once("idle", apply);
  }, [values, ramp]);

  return <div ref={el} style={{ height: "min(62vh, 620px)", minHeight: 360, ...style }} />;
}
