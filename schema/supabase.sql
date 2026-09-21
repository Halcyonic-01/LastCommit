-- VarshaDrishti Supabase schema: subscribers, rain reports, broadcast + notification log.
-- Run once in the Supabase SQL editor for a new project. Idempotent (safe to re-run).
--
-- Five tables, three trust levels:
--   rain_reports  farmer-submitted ground truth. Anon can INSERT (the PWA has no login)
--                 and SELECT (P9: dots on the officer map). No PII — an area id and a
--                 rain level, nothing that identifies who sent it.
--   subscribers   phone numbers / chat ids. Service-role only — never readable by anon.
--   broadcasts    audit log of what was sent, when, to how many. Service-role only.
--   farmer_messages advisories sent to an area's farmers, read by the PWA's notification
--                 page. Anon can SELECT (that is the delivery); only service_role writes.
--                 No PII — an area id and the advisory text, nothing about a person.
--   notifications one row per farmer per message: the advice, the channel, the delivery
--                 status. Service-role only — it holds a destination and a name.

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

-- Optional, added for the notification console: a name to show an officer instead of a
-- masked phone number. Nullable — every existing row predates it and stays valid.
alter table subscribers add column if not exists name text;

create index if not exists subscribers_area_channel on subscribers (area_id, channel) where active;

alter table subscribers enable row level security;

-- Anon may register a farmer's own WhatsApp/SMS number from the onboarding screen, and
-- never read anything back (no select policy below). 'telegram' stays in the channel
-- list only so that rows created before that channel was retired remain valid; nothing
-- in the tree sends to it. The farmer's real delivery path is farmer_messages below.
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

-- --- notifications ---------------------------------------------------------------
-- One row per farmer per message, written by services/notify/dispatcher.py after the
-- rules engine has already produced the advice. `broadcasts` above stays as it is: it
-- counts sends per area, this records them per person, with the text that went out.
--
-- `simulated` is the honest bit. WhatsApp Cloud API is metered, so until the two Meta
-- credentials are set the WhatsApp provider composes the message and sends nothing —
-- those rows land here with simulated = true and must never be read as a delivery.

create table if not exists notifications (
  id                   uuid primary key default gen_random_uuid(),
  created_at           timestamptz not null default now(),
  sent_at              timestamptz,

  area_id              text not null,
  area_name            text,
  district             text,

  farmer_name          text,
  destination          text not null,      -- phone number or chat id; never returned to a browser
  crop                 text,
  stage                text,
  lang                 text not null default 'kn',

  severity             text,               -- the advisory's own CRIDA severity
  risk_event           text,               -- p_onset | p_false_onset | p_dry7 | p_dry14 | p_heavy
  risk_lead            text,               -- w1 | w2 | w3 | w4
  risk_p               real,
  rule_id              text,               -- which CRIDA rule produced the advice
  recommendation_en    text,
  recommendation_kn    text,
  source_table         text,               -- the CRIDA table it cites
  message              text,               -- the exact text dispatched

  channel              text not null check (channel in ('inapp', 'whatsapp', 'sms')),
  provider             text not null,      -- e.g. 'Farmer app' | 'WhatsApp (simulated)'
  simulated            boolean not null default false,
  status               text not null default 'queued'
                         check (status in ('queued', 'sent', 'delivered', 'read', 'failed')),
  provider_message_id  text,
  error                text,
  triggered_by         text not null default 'officer-console'
);

create index if not exists notifications_created_at on notifications (created_at desc);
create index if not exists notifications_area on notifications (area_id, created_at desc);

alter table notifications enable row level security;
-- no policies -> service_role only, same reasoning as subscribers and broadcasts

-- --- farmer_messages -------------------------------------------------------------
-- What the officer actually sends, and what the PWA's notification page reads back.
--
-- Addressed by area, not by person: one row serves every farmer whose app is set to
-- that hobli. That is why anon may read it — there is nothing here about anybody. It
-- is the same trust level as rain_reports, in the opposite direction.

create table if not exists farmer_messages (
  id            uuid primary key default gen_random_uuid(),
  created_at    timestamptz not null default now(),
  area_id       text not null,
  body          text not null,       -- the composed advisory, exactly as sent
  severity      text,                -- the advisory's own CRIDA severity
  rule_id       text,
  source_table  text,                -- the CRIDA table it cites
  risk_event    text,
  risk_lead     text,
  risk_p        real,
  sent_by       text not null default 'officer'
);

create index if not exists farmer_messages_area on farmer_messages (area_id, created_at desc);

alter table farmer_messages enable row level security;

-- Reading one's own area's advisories IS the delivery — the PWA has no login, so this
-- is anon by necessity and safe by construction (no PII in the table at all).
drop policy if exists farmer_messages_anon_select on farmer_messages;
create policy farmer_messages_anon_select on farmer_messages
  for select to anon
  using (true);
-- no insert policy -> only the officer's service-role process can send
