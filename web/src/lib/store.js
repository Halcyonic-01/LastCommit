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
import { supabase } from "./supabase.js";

const OUTBOX = "vd.outbox.v1";
const MAX_QUEUED = 200;                                  // ~a season of daily reports

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

// App.jsx, the 'online' event, and a manual submit() can all call flushOutbox() around
// the same moment; without this guard, two concurrent calls both read the same
// not-yet-cleared queue and both insert it, duplicating the row in Supabase.
let flushing = false;

/** Send whatever is queued. Not configured, no network, or already flushing -> no-op. */
export async function flushOutbox() {
  const q = readOutbox();
  if (!q.length || !supabase || !navigator.onLine || flushing) return { sent: 0, pending: q.length };
  flushing = true;
  try {
    // area_id/level/observed_on only — id and created_at are the table's to assign.
    const rows = q.map((r) => ({ area_id: r.area_id, level: r.level, observed_on: r.observed_on, source: "web" }));
    const { error } = await supabase.from("rain_reports").insert(rows);
    if (error) throw error;
    writeOutbox([]);
    return { sent: q.length, pending: 0 };
  } catch {
    return { sent: 0, pending: q.length };  // keep them; the next online event retries
  } finally {
    flushing = false;
  }
}

// --- phone registration ------------------------------------------------------
// Unlike prefs above, a submitted number is NOT device-only — it goes to Supabase
// so services/whatsapp/send.py and services/sms/send.py can reach this farmer
// directly. Kept out of the `vd.prefs.v2` blob so that blob's own "never sent
// anywhere" contract stays true for what it actually describes.
const PHONE_KEY = "vd.phone.v1";

/** 10 local digits -> {whatsapp, sms} in each API's own required format — Meta wants
 * no leading +, Twilio requires one. null if it's not 10 digits once cleaned. */
export function normalizePhone(digits) {
  const clean = String(digits ?? "").replace(/\D/g, "");
  if (clean.length !== 10) return null;
  return { whatsapp: `91${clean}`, sms: `+91${clean}` };
}

export function savedPhone() {
  try {
    return localStorage.getItem(PHONE_KEY) || "";
  } catch {
    return "";
  }
}

/** Register a farmer's own number for both channels. Optional by design — every
 * failure path (bad format, unconfigured Supabase, already registered, offline)
 * returns a status rather than throwing, since onboarding must never block on this. */
export async function registerPhone({ digits, areaId, lang }) {
  if (savedPhone() === digits) return { status: "already-saved" };
  const numbers = normalizePhone(digits);
  if (!numbers) return { status: "bad-format" };
  if (!supabase) return { status: "not-configured" };

  const rows = [
    { area_id: areaId, channel: "whatsapp", destination: numbers.whatsapp, lang, active: true },
    { area_id: areaId, channel: "sms", destination: numbers.sms, lang, active: true },
  ];
  const { error } = await supabase.from("subscribers").insert(rows);
  // 23505 = unique_violation (channel, destination) — this number is already in,
  // which is the outcome we wanted, not a failure to surface.
  if (error && error.code !== "23505") return { status: "failed" };

  try { localStorage.setItem(PHONE_KEY, digits); } catch { /* best-effort only */ }
  return { status: "saved" };
}
