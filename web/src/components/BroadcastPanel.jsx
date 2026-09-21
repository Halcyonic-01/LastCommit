import { useEffect, useState } from "react";

// The dashboard has no backend of its own yet (Vercel isn't linked — see
// IMPLEMENTATION_PLAN.md), so "Review broadcast" talks to services/broadcast_server.py
// running on the officer's own machine. Hardcoded, not an env var: this is a fixed
// local port by design, not a deployment target. Exported so Officer.jsx's
// subscriber-count fetch hits the same server without a second hardcoded copy.
export const BROADCAST_API = "http://localhost:8787";
const TOKEN_KEY = "vd.officer.token";

const CHANNEL_LABEL = { telegram: "Telegram", whatsapp: "WhatsApp", sms: "SMS" };

/** Broadcast review: real preview text, a real recipient send, never a one-tap fire. */
export default function BroadcastPanel({ areaIds, areaNames, event, lead, onClose, onSent }) {
  const [health, setHealth] = useState(null);       // null=loading | "down" | {token_set, configured}
  const [preview, setPreview] = useState(null);      // null=loading | "down" | {text}
  const [token, setToken] = useState(() => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } });
  const [channels, setChannels] = useState(new Set());
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    fetch(`${BROADCAST_API}/api/health`).then((r) => r.json())
      .then((h) => { setHealth(h); setChannels(new Set(Object.keys(h.configured).filter((c) => h.configured[c]))); })
      .catch(() => setHealth("down"));
    fetch(`${BROADCAST_API}/api/preview?areaId=${encodeURIComponent(areaIds[0])}`).then((r) => r.json())
      .then((p) => setPreview(p.text ? p : "down")).catch(() => setPreview("down"));
  }, [areaIds]);

  const setTokenAndSave = (v) => {
    setToken(v);
    try { localStorage.setItem(TOKEN_KEY, v); } catch { /* device won't remember it next time, still usable now */ }
  };

  const toggleChannel = (c) => setChannels((s) => {
    const next = new Set(s);
    next.has(c) ? next.delete(c) : next.add(c);
    return next;
  });

  async function send() {
    setSending(true);
    setResult(null);
    try {
      const r = await fetch(`${BROADCAST_API}/api/broadcast`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, areaIds, event, lead, channels: [...channels] }),
      });
      const body = await r.json();
      setResult(r.ok ? { ok: true, ...body } : { ok: false, error: body.error || `HTTP ${r.status}` });
      if (r.ok && body.sent > 0) onSent?.();
    } catch {
      setResult({ ok: false, error: "could not reach the broadcast server" });
    } finally {
      setSending(false);
    }
  }

  const down = health === "down";
  const canSend = !down && token && channels.size > 0 && !sending;

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(10,12,14,.72)", display: "flex",
      alignItems: "center", justifyContent: "center", zIndex: 50, padding: 20 }}>
      <div style={{ background: "var(--paper2)", border: "1px solid var(--rule2)", maxWidth: 560, width: "100%",
        maxHeight: "88vh", overflowY: "auto" }}>
        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--rule2)", display: "flex",
          justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Review broadcast</div>
          <button type="button" onClick={onClose} className="ops-mono" style={{ fontSize: 12, background: "none", border: "none", color: "var(--ink3)" }}>CLOSE ✕</button>
        </div>

        <div style={{ padding: 20 }}>
          {down ? (
            <div style={{ borderLeft: "3px solid var(--risk)", paddingLeft: 12, fontSize: 13, color: "var(--ink2)" }}>
              <div className="ops-mono" style={{ color: "var(--risk)", fontSize: 11, letterSpacing: ".06em" }}>BROADCAST SERVER NOT RUNNING</div>
              <div style={{ marginTop: 6 }}>Start it on this machine, then reopen this panel:</div>
              <div className="ops-mono" style={{ marginTop: 6, background: "var(--paper3)", padding: "8px 10px", fontSize: 12 }}>
                .venv/bin/python services/broadcast_server.py
              </div>
            </div>
          ) : (
            <>
              <div className="ops-mono" style={{ fontSize: 10, letterSpacing: ".1em", color: "var(--ink3)" }}>
                {areaIds.length} TALUK{areaIds.length === 1 ? "" : "S"} · {areaNames.join(", ")}
              </div>

              <div style={{ marginTop: 14 }}>
                <div className="ops-mono" style={{ fontSize: 10, letterSpacing: ".1em", color: "var(--ink3)" }}>
                  MESSAGE PREVIEW — {areaNames[0]}{areaIds.length > 1 ? ` (+${areaIds.length - 1} more, same template)` : ""}
                </div>
                <div className="kn" style={{ marginTop: 8, background: "var(--paper3)", padding: "10px 12px", fontSize: 14, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                  {preview === null ? "loading…" : preview === "down" ? "could not load a preview" : preview.text}
                </div>
              </div>

              <div style={{ marginTop: 16 }}>
                <div className="ops-mono" style={{ fontSize: 10, letterSpacing: ".1em", color: "var(--ink3)" }}>SEND VIA</div>
                <div style={{ display: "flex", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
                  {Object.keys(CHANNEL_LABEL).map((c) => {
                    const configured = health?.configured?.[c];
                    return (
                      <label key={c} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13,
                        color: configured ? "var(--ink)" : "var(--ink3)", opacity: configured ? 1 : .6 }}>
                        <input type="checkbox" disabled={!configured} checked={channels.has(c)} onChange={() => toggleChannel(c)}
                          style={{ accentColor: "var(--water2)", width: 15, height: 15 }} />
                        {CHANNEL_LABEL[c]}{!configured ? " (not configured)" : ""}
                      </label>
                    );
                  })}
                </div>
              </div>

              <div style={{ marginTop: 16 }}>
                <div className="ops-mono" style={{ fontSize: 10, letterSpacing: ".1em", color: "var(--ink3)" }}>OFFICER PASSCODE</div>
                <input type="password" value={token} onChange={(e) => setTokenAndSave(e.target.value)}
                  placeholder="OFFICER_BROADCAST_TOKEN" aria-label="Officer passcode"
                  style={{ marginTop: 6, width: "100%", minHeight: 40, border: "1px solid var(--rule2)", padding: "0 10px", fontSize: 13, background: "var(--paper3)" }} />
                {!health?.token_set ? (
                  <div style={{ marginTop: 6, fontSize: 11.5, color: "var(--risk)" }}>
                    The server has no OFFICER_BROADCAST_TOKEN set — every send will be rejected until .env has one.
                  </div>
                ) : null}
              </div>

              {result ? (
                <div style={{ marginTop: 16, borderLeft: `3px solid ${result.ok ? "var(--ok)" : "var(--risk)"}`, paddingLeft: 12, fontSize: 13 }}>
                  {result.ok
                    ? `Sent to ${result.sent} recipient${result.sent === 1 ? "" : "s"}${result.failed ? `, ${result.failed} failed` : ""}.`
                    : `Not sent: ${result.error}`}
                </div>
              ) : null}
            </>
          )}
        </div>

        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--rule2)", display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose} className="ops-mono"
            style={{ padding: "9px 16px", fontSize: 12, background: "var(--paper3)", border: "none", color: "var(--ink2)" }}>
            Cancel
          </button>
          {!down ? (
            <button type="button" onClick={send} disabled={!canSend}
              style={{ padding: "9px 18px", fontSize: 13, fontWeight: 700, border: "none",
                background: canSend ? "var(--water2)" : "var(--paper3)", color: canSend ? "var(--paper2)" : "var(--ink3)" }}>
              {sending ? "Sending…" : `Send to ${areaIds.length} taluk${areaIds.length === 1 ? "" : "s"} →`}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
