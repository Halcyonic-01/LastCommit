// Unread badge state. Per-viewer and cosmetic, so localStorage is the right home —
// a private window that loses it shows one extra badge, which costs nobody anything.
const SEEN_KEY = "vd.messages.seen";

export function lastSeen() {
  try { return localStorage.getItem(SEEN_KEY) || ""; } catch { return ""; }
}

export function markMessagesSeen(iso) {
  try { if (iso > lastSeen()) localStorage.setItem(SEEN_KEY, iso); } catch { /* badge stays, nothing breaks */ }
}

// Supabase is the real delivery path and the only one that reaches a phone. When it
// cannot answer — unconfigured, or schema/supabase.sql not run yet — the officer's own
// broadcast server on this machine serves the same rows, which keeps the whole
// officer -> farmer loop demonstrable on one laptop.
const LOCAL_API = import.meta.env.VITE_BROADCAST_API || "http://localhost:8787";
let _warned = false;

/** An area's advisories, newest first. Never throws: a farmer sees "no messages". */
export async function fetchMessages(supabase, areaId, limit = 30) {
  if (!areaId) return [];
  if (supabase) {
    const { data, error } = await supabase.from("farmer_messages")
      .select("*").eq("area_id", areaId)
      .order("created_at", { ascending: false }).limit(limit);
    // A farmer must never read a Postgres error; fall through to the local server.
    if (!error && data) return data;
    // Once is information; on every poll it is noise that buries real errors.
    if (error && !_warned) { _warned = true; console.warn("farmer_messages:", error.message); }
  }
  try {
    const r = await fetch(`${LOCAL_API}/api/farmer-messages?areaId=${encodeURIComponent(areaId)}`,
      { signal: AbortSignal.timeout(1500) });
    if (!r.ok) return [];
    return (await r.json()).messages || [];
  } catch {
    return [];
  }
}

/** Newest message timestamp for an area, or "" — used only to decide the badge. */
export async function newestMessageAt(supabase, areaId) {
  const rows = await fetchMessages(supabase, areaId, 1);
  return rows[0]?.created_at || "";
}
