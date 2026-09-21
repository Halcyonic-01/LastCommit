// Supabase client for the browser — anon key only, safe to expose. RLS decides what
// anon can actually touch (schema/supabase.sql): insert + select on rain_reports,
// select-only on farmer_messages (that read IS how an advisory reaches a farmer),
// insert-only on subscribers from onboarding's phone field — never readable back —
// and nothing at all on broadcasts or notifications.
import { createClient } from "@supabase/supabase-js";

const URL = import.meta.env.VITE_SUPABASE_URL;
const KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;

// null when unconfigured, so every caller checks rather than crashes on a fresh clone.
export const supabase = URL && KEY ? createClient(URL, KEY) : null;
