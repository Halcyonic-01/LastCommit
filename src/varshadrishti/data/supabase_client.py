"""Thin Supabase wrapper: subscribers, rain reports, broadcast log.

Server-side only — uses the service key, which must never reach the browser (the
frontend gets its own anon-key client, see web/src/lib/supabase.js). Every function
degrades to None/[]/False rather than raising when Supabase isn't configured or the
`supabase` package isn't installed, so scripts keep working locally without it — the
same fallback shape services/telegram/send.py already uses for its local subscribers.json.
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
    return q.execute().data or []


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
                   lang: str = "kn", crop: str | None = None) -> bool:
    """Register (or reactivate/update) one subscriber. False if unconfigured or it fails.

    Upserts on (channel, destination) — the schema's own unique constraint — so running
    setup again for someone already registered updates their row instead of duplicating it.
    """
    sb = client()
    if sb is None:
        return False
    try:
        sb.table("subscribers").upsert(
            {"area_id": area_id, "channel": channel, "destination": destination,
             "lang": lang, "crop": crop, "active": True},
            on_conflict="channel,destination",
        ).execute()
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
    return q.execute().data or []
