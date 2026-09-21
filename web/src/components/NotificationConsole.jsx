import { useEffect, useMemo, useState } from "react";
import { createNotification, getNotifications } from "../lib/api.js";

const riskFor = (p) => p >= 0.5 ? "high" : p >= 0.25 ? "caution" : "ok";
const label = { high: "HIGH", caution: "CAUTION", ok: "OK" };
const dateText = (value) => value ? new Date(value).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—";

export default function NotificationConsole({ rows, lead, forecastDate }) {
  const [selected, setSelected] = useState(rows[0] || null);
  const [farmerName, setFarmerName] = useState("");
  const [phone, setPhone] = useState("");
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  useEffect(() => { if (!selected && rows[0]) setSelected(rows[0]); }, [rows, selected]);
  const recommendation = selected?.advisories?.[0] || {
    action_en: "Monitor local field conditions and follow the forecast.",
    action_kn: "ಸ್ಥಳೀಯ ಹೊಲದ ಪರಿಸ್ಥಿತಿಯನ್ನು ಗಮನಿಸಿ ಮತ್ತು ಮುನ್ಸೂಚನೆಯನ್ನು ಅನುಸರಿಸಿ.",
  };
  const risk = selected ? riskFor(selected.p_dry7[lead]) : "ok";
  const location = selected ? `${selected.name_en}, ${selected.district_en}` : "";

  const refresh = () => getNotifications().then((data) => setNotifications(data.notifications || [])).catch((e) => setError(e.message)).finally(() => setLoading(false));
  useEffect(() => { refresh(); }, []);

  const send = async () => {
    setError(null); setNotice(null);
    if (!selected) return setError("Choose a farmer location first.");
    if (!farmerName.trim() || farmerName.trim().length < 2) return setError("Enter a valid farmer name (at least 2 characters).");
    if (!location) return setError("The selected farmer location is invalid.");
    setSending(true);
    try {
      const result = await createNotification({
        idempotency_key: `${farmerName.trim().toLowerCase()}|${selected.area_id}|${lead}|${forecastDate}`,
        farmer: { name: farmerName.trim(), location, phone: phone.trim() },
        crop: recommendation.crop || "ragi",
        risk_level: risk,
        recommendation: { action_en: recommendation.action_en, action_kn: recommendation.action_kn || recommendation.action_en, rule_id: recommendation.rule_id || "manual" },
        channel: "whatsapp",
      });
      setNotice(result.duplicate ? "Duplicate send prevented; the existing notification is shown below." : "Alert recorded as SIMULATED / DEMO. No WhatsApp message was sent.");
      refresh();
    } catch (e) { setError(e.message); }
    finally { setSending(false); }
  };

  const preview = useMemo(() => [
    "VarshaDrishti weather alert",
    farmerName || "Farmer name",
    location || "Farmer location",
    `Risk: ${label[risk]}`,
    recommendation.action_en,
  ].join("\n"), [farmerName, location, risk, recommendation]);

  return <section style={{ borderTop: "1px solid var(--rule2)", padding: "20px" }}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
      <div><div style={{ fontSize: 18, fontWeight: 800 }}>Notification Console</div><div className="ops-mono" style={{ color: "var(--ink3)", fontSize: 10.5, marginTop: 4 }}>RECOMMENDATION → DISPATCHER → WHATSAPP · SIMULATED / DEMO</div></div>
      <div className="ops-mono" style={{ color: "var(--wait)", fontSize: 11 }}>NO REAL WHATSAPP DELIVERY</div>
    </div>
    <div className="notify-grid" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(260px,.7fr)", gap: 18, marginTop: 16 }}>
      <div>
        <label className="ops-mono" style={{ display: "block", fontSize: 10, color: "var(--ink3)" }}>FARMER LOCATION</label>
        <select value={selected?.area_id || ""} onChange={(e) => setSelected(rows.find((r) => r.area_id === e.target.value) || null)} style={{ width: "100%", padding: 9, marginTop: 5, background: "var(--paper2)", color: "var(--ink)", border: "1px solid var(--rule2)" }}>
          {rows.map((r) => <option key={r.area_id} value={r.area_id}>{r.name_en} · {r.district_en}</option>)}
        </select>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 10 }}>
          <input value={farmerName} onChange={(e) => setFarmerName(e.target.value)} placeholder="Farmer name *" aria-label="Farmer name" style={{ padding: 9, background: "var(--paper2)", color: "var(--ink)", border: "1px solid var(--rule2)" }} />
          <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Phone (optional demo)" aria-label="Phone" style={{ padding: 9, background: "var(--paper2)", color: "var(--ink)", border: "1px solid var(--rule2)" }} />
        </div>
        <div style={{ marginTop: 12, padding: 12, border: "1px solid var(--rule2)", background: "var(--paper2)", whiteSpace: "pre-line", lineHeight: 1.5 }}>{preview}</div>
        <button type="button" onClick={send} disabled={sending || !selected} style={{ marginTop: 12, padding: "10px 16px", background: sending ? "var(--paper3)" : "#5aa3dc", color: "#0d1418", border: 0, fontWeight: 800 }}>{sending ? "Recording…" : "Send Alert · WhatsApp DEMO"}</button>
        {error ? <div role="alert" style={{ color: "var(--risk)", marginTop: 10, fontSize: 12 }}>{error}</div> : null}
        {notice ? <div role="status" style={{ color: "var(--ok)", marginTop: 10, fontSize: 12 }}>{notice}</div> : null}
      </div>
      <div style={{ border: "1px solid var(--rule2)", padding: 14, background: "#142329" }}>
        <div className="ops-mono" style={{ fontSize: 10, color: "#5aa3dc", letterSpacing: ".1em" }}>WHATSAPP-STYLE PREVIEW</div>
        <div style={{ marginTop: 12, background: "#d9fdd3", color: "#172017", padding: 12, borderRadius: 8, whiteSpace: "pre-line", fontSize: 13, lineHeight: 1.45 }}>{preview}</div>
      </div>
    </div>
    <div style={{ marginTop: 24, borderTop: "1px solid var(--rule2)" }}>
      <div style={{ padding: "14px 0 8px", fontWeight: 700 }}>Notification history / logs <span className="ops-mono" style={{ color: "var(--ink3)", fontSize: 10 }}>({loading ? "…" : notifications.length})</span></div>
      {notifications.length === 0 && !loading ? <div style={{ color: "var(--ink3)", fontSize: 13 }}>No alerts recorded yet.</div> : null}
      <div style={{ overflowX: "auto" }}><table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, minWidth: 760 }}><thead><tr>{["FARMER / LOCATION", "CROP", "RISK", "RECOMMENDATION", "CHANNEL", "TIMESTAMP", "STATUS"].map((h) => <th key={h} className="ops-mono" style={{ textAlign: "left", color: "var(--ink3)", fontSize: 9.5, padding: "8px 6px", borderBottom: "1px solid var(--rule2)" }}>{h}</th>)}</tr></thead><tbody>{notifications.map((n) => <tr key={n.id}><td style={{ padding: "8px 6px", borderBottom: "1px solid var(--rule)" }}><b>{n.farmer?.name}</b><br /><span style={{ color: "var(--ink3)" }}>{n.farmer?.location}</span></td><td style={{ padding: 6, borderBottom: "1px solid var(--rule)" }}>{n.crop}</td><td style={{ padding: 6, borderBottom: "1px solid var(--rule)", color: n.risk_level === "high" ? "var(--risk)" : "var(--wait)" }}>{label[n.risk_level] || n.risk_level}</td><td style={{ padding: 6, borderBottom: "1px solid var(--rule)", maxWidth: 260 }}>{n.recommendation?.action_en}</td><td style={{ padding: 6, borderBottom: "1px solid var(--rule)" }}>WhatsApp<br /><span style={{ color: "var(--wait)", fontSize: 10 }}>{n.channel_mode}</span></td><td className="ops-mono" style={{ padding: 6, borderBottom: "1px solid var(--rule)", color: "var(--ink3)", fontSize: 10 }}>{dateText(n.created_at)}</td><td style={{ padding: 6, borderBottom: "1px solid var(--rule)", color: "var(--ok)", whiteSpace: "nowrap" }}>{n.status === "simulated" ? "SIMULATED" : n.status}</td></tr>)}</tbody></table></div>
    </div>
  </section>;
}
