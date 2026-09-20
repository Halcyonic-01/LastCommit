// Supabase client for the browser — anon key only, safe to expose. RLS decides what
// anon can actually touch (schema/supabase.sql): insert + select on rain_reports,
// nothing on subscribers or broadcasts.
import { createClient } from "@supabase/supabase-js";

const URL = import.meta.env.VITE_SUPABASE_URL;
const KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;

// null when unconfigured, so every caller checks rather than crashes on a fresh clone.
export const supabase = URL && KEY ? createClient(URL, KEY) : null;
