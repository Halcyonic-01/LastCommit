import { useEffect, useState } from "react";
import { BROADCAST_API, getToken, setToken } from "../lib/officer.js";

// Farmer app first: it is the default, it really delivers, and it costs nothing.
const CHANNEL_LABEL = { inapp: "Farmer app", whatsapp: "WhatsApp", sms: "SMS" };

/** Broadcast review: real preview text, a real recipient send, never a one-tap fire. */
export default function BroadcastPanel({ areaIds, areaNames, event, lead, onClose, onSent }) {
  const [health, setHealth] = useState(null);       // null=loading | "down" | {token_set, configured}
  const [sim, setSim] = useState(null);              // per-channel provider + simulated flag
  const [preview, setPreview] = useState(null);      // null=loading | "down" | {text}
  const [token, setTokenState] = useState(getToken);
  const [channels, setChannels] = useState(new Set());
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    fetch(`${BROADCAST_API}/api/health`).then((r) => r.json())
      .then((h) => { setHealth(h); setChannels(new Set(h.configured.inapp ? ["inapp"] : [])); })
      .catch(() => setHealth("down"));
    fetch(`${BROADCAST_API}/api/preview?areaId=${encodeURIComponent(areaIds[0])}`).then((r) => r.json())
      .then((p) => setPreview(p.text ? p : "down")).catch(() => setPreview("down"));
    fetch(`${BROADCAST_API}/api/notification-channels`).then((r) => r.json())
      .then((b) => setSim(b.channels)).catch(() => {});
  }, [areaIds]);

  const setTokenAndSave = (v) => { setTokenState(v); setToken(v); };

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
                        {CHANNEL_LABEL[c]}{sim?.[c]?.simulated ? " (simulated)" : !configured ? " (not configured)" : ""}
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
                <div style={{ marginTop: 16, fontSize: 13, paddingLeft: 12,
                  borderLeft: `3px solid ${!result.ok || result.failed ? "var(--risk)" : result.sent ? "var(--ok)" : "var(--wait)"}` }}>
                  {result.ok
                    ? <>
                        <div>
                          {result.sent > 0
                            ? `Delivered to ${result.sent} destination${result.sent === 1 ? "" : "s"}. Farmers see it on their Messages screen.`
                            : "Nothing was delivered."}
                          {result.failed ? ` ${result.failed} failed.` : ""}
                          {result.skipped ? ` ${result.skipped} skipped.` : ""}
                        </div>
                        {(result.results || []).filter((r) => r.error).map((r, i) => (
                          <div key={i} className="ops-mono" style={{ fontSize: 11, color: "var(--ink2)", marginTop: 4 }}>
                            {r.channel}: {r.error}
                          </div>
                        ))}
                      </>
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
