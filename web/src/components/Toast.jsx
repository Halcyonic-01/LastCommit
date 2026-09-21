import { useEffect } from "react";

// A send is the one action here that leaves the officer's machine, and the panel it was
// launched from closes on success — so without this the screen just goes quiet and the
// only confirmation is a row appearing in a table somewhere else.
export default function Toast({ message, tone = "ok", onDone, ms = 4500 }) {
  useEffect(() => {
    if (!message) return undefined;
    const timer = setTimeout(() => onDone?.(), ms);
    return () => clearTimeout(timer);
  }, [message, ms, onDone]);

  if (!message) return null;
  const edge = tone === "risk" ? "var(--risk)" : tone === "wait" ? "var(--wait)" : "var(--ok)";
  return (
    <div role="status" aria-live="polite"
      style={{ position: "fixed", left: "50%", bottom: 28, transform: "translateX(-50%)",
        zIndex: 60, background: "var(--paper2)", color: "var(--ink)",
        border: "1px solid var(--rule2)", borderLeft: `4px solid ${edge}`,
        padding: "12px 18px", maxWidth: "min(92vw, 520px)", fontSize: 13.5,
        boxShadow: "0 6px 22px rgba(10,12,14,.28)", display: "flex", gap: 10, alignItems: "center" }}>
      {/* Only a real success gets a tick. A "nothing was delivered" notice wearing a
          checkmark is worse than no notice at all. */}
      <span aria-hidden="true" style={{ color: edge, fontWeight: 800 }}>
        {tone === "ok" ? "✓" : "!"}
      </span>
      <span>{message}</span>
    </div>
  );
}
