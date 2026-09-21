-- VarshaDrishti Supabase schema: subscribers, rain reports, broadcast log.
-- Run once in the Supabase SQL editor for a new project. Idempotent (safe to re-run).
--
-- Three tables, three trust levels:
--   rain_reports  farmer-submitted ground truth. Anon can INSERT (the PWA has no login)
--                 and SELECT (P9: dots on the officer map). No PII — an area id and a
--                 rain level, nothing that identifies who sent it.
--   subscribers   phone numbers / chat ids. Service-role only — never readable by anon.
--   broadcasts    audit log of what was sent, when, to how many. Service-role only.

create extension if not exists pgcrypto;  -- gen_random_uuid()

-- --- rain_reports -----------------------------------------------------------

create table if not exists rain_reports (
  id           uuid primary key default gen_random_uuid(),
  area_id      text not null,
  level        text not null check (level in ('none', 'light', 'heavy')),
  observed_on  date not null,          -- the day being reported on, not the send time
  source       text not null default 'web',
  created_at   timestamptz not null default now()
);

create index if not exists rain_reports_area_date on rain_reports (area_id, observed_on desc);

alter table rain_reports enable row level security;

drop policy if exists rain_reports_anon_insert on rain_reports;
create policy rain_reports_anon_insert on rain_reports
  for insert to anon
  with check (level in ('none', 'light', 'heavy'));

drop policy if exists rain_reports_anon_select on rain_reports;
create policy rain_reports_anon_select on rain_reports
  for select to anon
  using (true);

-- --- subscribers --------------------------------------------------------------

create table if not exists subscribers (
  id           uuid primary key default gen_random_uuid(),
  area_id      text not null,
  channel      text not null check (channel in ('telegram', 'whatsapp', 'sms')),
  destination  text not null,          -- chat id (telegram) or phone number (whatsapp/sms)
  lang         text not null default 'kn',
  crop         text,
  active       boolean not null default true,
  created_at   timestamptz not null default now(),
  unique (channel, destination)
);

create index if not exists subscribers_area_channel on subscribers (area_id, channel) where active;

alter table subscribers enable row level security;

-- Anon may register a farmer's own WhatsApp/SMS number from the onboarding screen —
-- but never a Telegram row (those only ever come from the bot's own /start discovery,
-- see scripts/telegram_setup.py) and never read anything back (no select policy below).
-- The length check is a spam floor, not real validation — real validation is client-side.
drop policy if exists subscribers_anon_insert on subscribers;
create policy subscribers_anon_insert on subscribers
  for insert to anon
  with check (channel in ('whatsapp', 'sms') and length(destination) between 8 and 20);
-- no select policy -> anon can add a number but never read the list back

-- --- broadcasts -----------------------------------------------------------------

create table if not exists broadcasts (
  id               uuid primary key default gen_random_uuid(),
  sent_at          timestamptz not null default now(),
  area_ids         text[] not null,
  event            text not null,      -- p_onset | p_false_onset | p_dry7 | p_dry14 | p_heavy
  lead             text not null,      -- w1 | w2 | w3 | w4
  channel          text not null check (channel in ('telegram', 'whatsapp', 'sms')),
  recipient_count  integer not null default 0,
  dry_run          boolean not null default false,
  triggered_by     text not null default 'manual'
);

create index if not exists broadcasts_sent_at on broadcasts (sent_at desc);

alter table broadcasts enable row level security;
-- no policies -> service_role only, same reasoning as subscribers
