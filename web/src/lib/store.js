// The farmer picks a language, a hobli and a crop once. Kept per-device, never sent anywhere.
const KEY = "vd.prefs.v2";
// `place` is resolved once, at onboarding, from the index that screen already
// loaded. Today then needs no second request on a 2G phone.
const DEFAULTS = {
  areaId: "KGIS-H-180901", crop: "ragi", lang: "kn", onboarded: false,
  place: { taluk_kn: "", taluk_en: "", district_kn: "" },
};

export function loadPrefs() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return { ...DEFAULTS }; // private window or cleared storage — fall back, never crash
  }
}

export function savePrefs(patch) {
  const next = { ...loadPrefs(), ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage blocked — the session still works, the choice just won't persist */
  }
  return next;
}

// --- rain reports -----------------------------------------------------------
// A farmer taps "send" in a field with no bars. The report lands in a local
// outbox first and leaves later — dropping it because the network was down
// would lose exactly the ground truth the forecast is being corrected against.
const OUTBOX = "vd.outbox.v1";
const MAX_QUEUED = 200;                                  // ~a season of daily reports
const ENDPOINT = import.meta.env.VITE_REPORT_ENDPOINT || "";  // unset until P6 stands one up

export function readOutbox() {
  try {
    const q = JSON.parse(localStorage.getItem(OUTBOX) || "[]");
    return Array.isArray(q) ? q : [];
  } catch {
    return [];
  }
}

function writeOutbox(q) {
  try {
    localStorage.setItem(OUTBOX, JSON.stringify(q.slice(-MAX_QUEUED)));
    return true;
  } catch {
    return false;  // storage blocked or full — the caller must not claim it was saved
  }
}

/** Queue one report. `level` is none|light|heavy; the question asks about yesterday. */
export function queueReport({ areaId, level }) {
  const now = new Date();
  const y = new Date(now.getTime() - 86400000);
  const r = {
    id: `${areaId}-${now.getTime()}`,
    area_id: areaId,
    level,
    observed_on: y.toISOString().slice(0, 10),
    created_at: now.toISOString(),
  };
  const stored = writeOutbox([...readOutbox(), r]);
  return { report: r, stored };
}

/** Send whatever is queued. No endpoint or no network -> everything stays put. */
export async function flushOutbox() {
  const q = readOutbox();
  if (!q.length || !ENDPOINT || !navigator.onLine) return { sent: 0, pending: q.length };
  try {
    const res = await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reports: q }),
    });
    if (!res.ok) throw new Error(String(res.status));
    writeOutbox([]);
    return { sent: q.length, pending: 0 };
  } catch {
    return { sent: 0, pending: q.length };  // keep them; the next online event retries
  }
}
