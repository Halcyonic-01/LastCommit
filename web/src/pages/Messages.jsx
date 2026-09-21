import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { loadPrefs } from "../lib/store.js";
import { supabase } from "../lib/supabase.js";
import { t } from "../i18n/strings.js";
import Tabs from "../components/Tabs.jsx";
import { Shell, Msg } from "../components/Frame.jsx";
import { Back } from "../components/Marks.jsx";
import { markMessagesSeen } from "../lib/messages.js";

const LIMIT = 30;

// The advisory text carries WhatsApp's own *bold*/_italic_ markers (services/advisory_text.py).
// Showing them raw is what a broken chat app looks like, so render them.
function Rich({ text }) {
  const parts = String(text).split(/(\*[^*\n]+\*|_[^_\n]+_)/g);
  return parts.map((p, i) => {
    if (p.startsWith("*") && p.endsWith("*") && p.length > 2)
      return <b key={i}>{p.slice(1, -1)}</b>;
    if (p.startsWith("_") && p.endsWith("_") && p.length > 2)
      return <i key={i} style={{ opacity: .82 }}>{p.slice(1, -1)}</i>;
    return <span key={i}>{p}</span>;
  });
}

const clock = (iso) => {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
};

export default function Messages() {
  const { areaId, lang } = loadPrefs();
  const [rows, setRows] = useState(null);   // null = loading

  useEffect(() => {
    if (!supabase) { setRows([]); return; }
    supabase.from("farmer_messages").select("*").eq("area_id", areaId)
      .order("created_at", { ascending: false }).limit(LIMIT)
      .then(({ data, error }) => {
        // A farmer must never read a Postgres error. Whatever went wrong, the screen
        // says "no messages yet"; the operator sees the real reason on the send side.
        if (error) { console.warn("farmer_messages:", error.message); setRows([]); return; }
        setRows(data || []);
      });
  }, [areaId]);

  // Opening the page is reading it — clear the badge on the way in, not on the way out,
  // so closing the app half-way through still counts as seen.
  useEffect(() => { if (rows?.length) markMessagesSeen(rows[0].created_at); }, [rows]);

  if (rows === null) return <Shell><Msg kind="loading" lang={lang} /><Tabs lang={lang} /></Shell>;

  return (
    <Shell>
      <div className="pad rule-b" style={{ paddingTop: 11, paddingBottom: 10, display: "flex", alignItems: "center", gap: 10 }}>
        <Link to="/today" aria-label={t("today", lang)} style={{ display: "flex", color: "var(--ink)" }}>
          <Back size={20} />
        </Link>
        <div className="kn" style={{ fontSize: 17, fontWeight: 700 }}>{t("messages", lang)}</div>
      </div>

      <div className="grow" style={{ background: "var(--paper3)", minHeight: 0 }}>
        {rows.length === 0 ? (
          <div className="pad" style={{ paddingTop: 34, textAlign: "center" }}>
            <div className="kn" style={{ fontSize: 16, fontWeight: 600 }}>{t("noMessages", lang)}</div>
            <div className="gloss" style={{ marginTop: 6 }}>{t("noMessagesHint", lang)}</div>
          </div>
        ) : (
          <div className="pad" style={{ paddingTop: 14, paddingBottom: 18, display: "flex", flexDirection: "column", gap: 12 }}>
            {/* newest first from the server; reversed so the newest sits at the bottom
                where a chat app puts it */}
            {[...rows].reverse().map((m) => (
              <div key={m.id} style={{ display: "flex" }}>
                <div className="kn" style={{ background: "#e8f6c8", borderRadius: "10px 10px 10px 2px",
                  padding: "10px 12px", fontSize: 15, lineHeight: 1.6, whiteSpace: "pre-wrap",
                  color: "#17140f", maxWidth: "92%", boxShadow: "0 1px 1px rgba(0,0,0,.13)" }}>
                  <Rich text={m.body} />
                  <div style={{ textAlign: "right", fontSize: 10.5, color: "#5e7a3a", marginTop: 6 }}>
                    {clock(m.created_at)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Tabs lang={lang} />
    </Shell>
  );
}
