"""Thin Supabase wrapper: subscribers, rain reports, broadcast log.

Server-side only — uses the service key, which must never reach the browser (the
frontend gets its own anon-key client, see web/src/lib/supabase.js). Every function
degrades to None/[]/False rather than raising when Supabase isn't configured or the
`supabase` package isn't installed, so scripts keep working locally without it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def client() -> Any | None:
    """-> a Supabase client, or None if unconfigured or the package is missing."""
    _load_env()
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        from supabase import create_client
    except ImportError:
        return None
    return create_client(url, key)


def fetch_subscribers(channel: str | None = None, area_id: str | None = None) -> list[dict]:
    """Active subscribers, optionally filtered to one channel and/or one area. [] if unconfigured."""
    sb = client()
    if sb is None:
        return []
    q = sb.table("subscribers").select("*").eq("active", True)
    if channel:
        q = q.eq("channel", channel)
    if area_id:
        q = q.eq("area_id", area_id)
    try:
        return q.execute().data or []
    except Exception:
        return []


def log_broadcast(*, area_ids: list[str], event: str, lead: str, channel: str,
                  recipient_count: int, dry_run: bool = False,
                  triggered_by: str = "manual") -> bool:
    """Record a send. Best-effort — a logging failure must never block the send itself."""
    sb = client()
    if sb is None:
        return False
    try:
        sb.table("broadcasts").insert({
            "area_ids": area_ids, "event": event, "lead": lead, "channel": channel,
            "recipient_count": recipient_count, "dry_run": dry_run,
            "triggered_by": triggered_by,
        }).execute()
        return True
    except Exception:
        return False


def add_subscriber(*, area_id: str, channel: str, destination: str,
                   lang: str = "kn", crop: str | None = None,
                   name: str | None = None) -> bool:
    """Register (or reactivate/update) one subscriber. False if unconfigured or it fails.

    Upserts on (channel, destination) — the schema's own unique constraint — so running
    setup again for someone already registered updates their row instead of duplicating it.
    """
    sb = client()
    if sb is None:
        return False
    row = {"area_id": area_id, "channel": channel, "destination": destination,
           "lang": lang, "crop": crop, "active": True}
    # Only when given: `name` is a later column, and a project that has not re-run
    # schema/supabase.sql yet must still be able to register a subscriber.
    if name is not None:
        row["name"] = name
    try:
        sb.table("subscribers").upsert(row, on_conflict="channel,destination").execute()
        return True
    except Exception:
        return False


def fetch_rain_reports(area_id: str | None = None, limit: int = 100) -> list[dict]:
    """Recent farmer rain reports, newest first. [] if unconfigured."""
    sb = client()
    if sb is None:
        return []
    q = sb.table("rain_reports").select("*").order("created_at", desc=True).limit(limit)
    if area_id:
        q = q.eq("area_id", area_id)
    try:
        return q.execute().data or []
    except Exception:
        return []


# --- notifications ------------------------------------------------------------
# Unlike the functions above, these return None (not []/False) when Supabase is
# unavailable, because the caller has a real second option: services/notify/store.py
# falls back to a local file and has to be able to tell "no rows" from "no database".

def insert_notification(row: dict) -> dict | None:
    """-> the stored row (with its server-side id), or None if Supabase can't take it."""
    sb = client()
    if sb is None:
        return None
    try:
        r = sb.table("notifications").insert(row).execute()
        return (r.data or [None])[0]
    except Exception:
        return None


def fetch_notifications(area_id: str | None = None, limit: int = 100) -> list[dict] | None:
    """Recent notifications, newest first. None if Supabase can't answer."""
    sb = client()
    if sb is None:
        return None
    try:
        q = sb.table("notifications").select("*").order("created_at", desc=True).limit(limit)
        if area_id:
            q = q.eq("area_id", area_id)
        return q.execute().data or []
    except Exception:
        return None


def fetch_notification(notification_id: str) -> dict | None:
    """One notification. None if Supabase can't answer; {} if no such id there."""
    sb = client()
    if sb is None:
        return None
    try:
        r = sb.table("notifications").select("*").eq("id", notification_id).limit(1).execute()
        return (r.data or [{}])[0]
    except Exception:
        return None


def update_notification(notification_id: str, patch: dict) -> dict | None:
    """Patch one notification. None if Supabase can't answer; {} if no such id there."""
    sb = client()
    if sb is None:
        return None
    try:
        r = sb.table("notifications").update(patch).eq("id", notification_id).execute()
        return (r.data or [{}])[0]  # {} = Supabase answered, but nothing matched
    except Exception:
        return None


# --- farmer_messages ----------------------------------------------------------
# The farmer-facing delivery path. Anon-readable by design (see schema/supabase.sql),
# so the PWA reads these directly with its own client — these helpers are the officer
# side of that exchange.

def insert_farmer_message(row: dict) -> dict | None:
    """Deliver one advisory to an area. -> the stored row, or None if it didn't land."""
    sb = client()
    if sb is None:
        return None
    try:
        r = sb.table("farmer_messages").insert(row).execute()
        return (r.data or [None])[0]
    except Exception:
        return None


def fetch_farmer_messages(area_id: str, limit: int = 30) -> list[dict] | None:
    """An area's advisories, newest first. None if Supabase can't answer."""
    sb = client()
    if sb is None:
        return None
    try:
        return (sb.table("farmer_messages").select("*").eq("area_id", area_id)
                .order("created_at", desc=True).limit(limit).execute().data or [])
    except Exception:
        return None
