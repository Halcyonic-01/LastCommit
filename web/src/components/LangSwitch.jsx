import { useState } from "react";
import { LANGS } from "../i18n/strings.js";
import { savePrefs } from "../lib/store.js";

/** Language, reachable from inside the app — not just the one-time onboarding pick.
 *  No global state in this app, so switching reloads: simplest correct fix given
 *  every page reads loadPrefs() fresh on mount rather than from shared context. */
export default function LangSwitch({ lang }) {
  const [open, setOpen] = useState(false);
  const current = LANGS.find((l) => l.code === lang) ?? LANGS[0];

  const pick = (code) => {
    if (code !== lang) { savePrefs({ lang: code }); window.location.reload(); }
    setOpen(false);
  };

  return (
    <div style={{ position: "relative" }}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-label="Change language"
        aria-expanded={open}
        className="kn" style={{ width: 38, height: 38, borderRadius: 19, border: "1.5px solid var(--ink)",
          background: "var(--paper2)", fontSize: 15, fontWeight: 800, display: "flex",
          alignItems: "center", justifyContent: "center" }}>
        {current.script.slice(0, 1)}
      </button>
      {open ? (
        <>
          <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
          <div style={{ position: "absolute", top: 44, right: 0, zIndex: 41, background: "var(--paper2)",
            border: "1.5px solid var(--ink)", minWidth: 148, boxShadow: "0 4px 14px rgba(0,0,0,.18)" }}>
            {LANGS.map((l) => (
              <button key={l.code} type="button" onClick={() => pick(l.code)} aria-pressed={l.code === lang}
                style={{ width: "100%", textAlign: "left", padding: "10px 14px", border: "none",
                  borderBottom: "1px solid var(--rule2)", background: l.code === lang ? "var(--paper3)" : "transparent",
                  display: "flex", alignItems: "baseline", gap: 8 }}>
                <span className="kn" style={{ fontSize: 16, fontWeight: 700 }}>{l.script}</span>
                <span style={{ fontSize: 10.5, color: "var(--ink3)", letterSpacing: ".04em" }}>{l.en}</span>
              </button>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
