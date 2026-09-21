// The officer tools have no real backend yet (Vercel isn't linked — see
// IMPLEMENTATION_PLAN.md): they talk to services/broadcast_server.py running on the
// officer's own machine. Hardcoded, not an env var — a fixed local port by design,
// not a deployment target. Lives here rather than in a component so the broadcast
// panel, the dashboard's subscriber counts and the notification console all agree.
export const BROADCAST_API = "http://localhost:8787";

const TOKEN_KEY = "vd.officer.token";

// The passcode never leaves this machine; localStorage may throw in private mode, so
// a failed read/write costs the officer a retype rather than breaking the screen.
export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}

export function setToken(v) {
  try { localStorage.setItem(TOKEN_KEY, v); } catch { /* not remembered next time, still usable now */ }
}

/** Officer-only GET: the passcode rides in a header, never in a URL. */
export async function officerGet(path) {
  const r = await fetch(`${BROADCAST_API}${path}`, { headers: { "X-Officer-Token": getToken() } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}

export async function officerPost(path, payload) {
  const r = await fetch(`${BROADCAST_API}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: getToken(), ...payload }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}
