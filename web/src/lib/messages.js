// Unread badge state. Per-viewer and cosmetic, so localStorage is the right home —
// a private window that loses it shows one extra badge, which costs nobody anything.
const SEEN_KEY = "vd.messages.seen";

export function lastSeen() {
  try { return localStorage.getItem(SEEN_KEY) || ""; } catch { return ""; }
}

export function markMessagesSeen(iso) {
  try { if (iso > lastSeen()) localStorage.setItem(SEEN_KEY, iso); } catch { /* badge stays, nothing breaks */ }
}

/** Newest message timestamp for an area, or "" — used only to decide the badge. */
export async function newestMessageAt(supabase, areaId) {
  if (!supabase || !areaId) return "";
  const { data, error } = await supabase.from("farmer_messages")
    .select("created_at").eq("area_id", areaId)
    .order("created_at", { ascending: false }).limit(1);
  if (error || !data?.length) return "";
  return data[0].created_at;
}
