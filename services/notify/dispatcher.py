"""The layer between a finished recommendation and a farmer's phone.

Nothing here predicts anything. By the time dispatch() runs, scripts/nightly.py has
already blended the models and rules/engine.py has already chosen the CRIDA action —
this reads forecast/area/<id>.json, works out who subscribed to that area, asks the
channel's provider to send, and writes one durable record per recipient. Swapping the
simulated WhatsApp provider for the real Cloud API changes nothing above this line.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "services"))

from varshadrishti.data import supabase_client as SB  # noqa: E402
from advisory_text import compose  # noqa: E402

from . import providers as P
from . import store as ST

AREA_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")  # also a path-traversal guard
PHONE_RE = re.compile(r"^\+?\d{8,15}$")       # E.164-ish; WhatsApp/SMS destinations
DUPLICATE_WINDOW_HOURS = 12  # one area gets one copy of one rule's advice per half-day

LEADS = ("w1", "w2", "w3", "w4")
EVENTS = ("p_onset", "p_false_onset", "p_dry7", "p_dry14", "p_heavy")


class DispatchError(ValueError):
    """A whole request is unusable — bad area, missing forecast, no recommendation."""


def _area_file(area_id: str) -> Path:
    if not AREA_ID_RE.match(area_id or ""):
        raise DispatchError("invalid area id")
    f = ROOT / "forecast" / "area" / f"{area_id}.json"
    if not f.exists():
        raise DispatchError("no forecast file for this area")
    return f


def load_recommendation(area_id: str, event: str = "p_dry7", lead: str = "w1") -> dict:
    """The already-generated recommendation for one area, flattened for a record.

    Raises rather than inventing anything: an area with no advisory has no advice to
    send, and the schema guarantees one, so its absence is a real failure to surface.
    """
    if event not in EVENTS:
        raise DispatchError(f"unknown event {event!r}")
    if lead not in LEADS:
        raise DispatchError(f"unknown lead {lead!r}")
    d = json.loads(_area_file(area_id).read_text(encoding="utf-8"))
    f = d["forecast"]
    advisories = f.get("advisories") or []
    if not advisories:
        raise DispatchError("this area carries no advisory — nothing to send")
    a = advisories[0]
    return {
        "area_id": area_id,
        "area_name": f.get("name_en", area_id),
        "district": f.get("district_en", ""),
        "severity": a.get("severity", "info"),
        "risk_event": event,
        "risk_lead": lead,
        "risk_p": float(f[event][lead]),
        "rule_id": a.get("rule_id", ""),
        "recommendation_en": a.get("action_en", ""),
        "recommendation_kn": a.get("action_kn", ""),
        "source_table": a.get("source", {}).get("table", ""),
        "message": compose(_area_file(area_id)),
        "crop": a.get("crop"),
        "stage": a.get("stage"),
    }


def validate(sub: dict) -> str | None:
    """-> a reason this subscriber can't be messaged, or None if they can."""
    dest = (sub.get("destination") or "").strip()
    if not dest:
        return "subscriber has no destination"
    channel = sub.get("channel", "")
    if channel in P.AREA_ADDRESSED:
        return None  # the address is an area id, not a phone number
    if channel in ("whatsapp", "sms") and not PHONE_RE.match(dest.replace(" ", "").replace("-", "")):
        return f"not a usable phone number: {mask(dest)}"
    if not (sub.get("area_id") or "").strip():
        return "subscriber has no area"
    return None


def mask(destination: str) -> str:
    """Never let a raw phone number or chat id out of this process."""
    d = (destination or "").strip()
    if len(d) <= 4:
        return "***"
    return f"{d[:3]}***{d[-2:]}"


def _recent_signatures(area_id: str) -> set[tuple]:
    """(channel, destination, rule_id) already sent for this area inside the window."""
    rows, _ = ST.recent(area_id=area_id, limit=200)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DUPLICATE_WINDOW_HOURS)
    seen = set()
    for r in rows:
        if r.get("status") == "failed":
            continue  # a failed attempt is not a delivery — resending is the point
        ts = r.get("created_at") or ""
        try:
            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= cutoff:
            seen.add((r.get("channel"), r.get("destination"), r.get("rule_id")))
    return seen


def audience(area_id: str, channel: str) -> list[dict]:
    """Who would be messaged, with destinations already masked — a pre-send review."""
    out = []
    for s in SB.fetch_subscribers(channel=channel, area_id=area_id):
        out.append({
            "farmer_name": s.get("name"),
            "destination_masked": mask(s.get("destination", "")),
            "area_id": s.get("area_id"),
            "crop": s.get("crop"),
            "lang": s.get("lang", "kn"),
            "invalid": validate(s),
        })
    return out


def dispatch(area_id: str, channel: str, *, event: str = "p_dry7", lead: str = "w1",
             force: bool = False, triggered_by: str = "officer-console",
             to: str | None = None) -> dict:
    """Send one area's current recommendation to one channel's subscribers.

    `to` overrides the subscriber list with a single destination — the same escape hatch
    services/whatsapp/send.py's --to gives, so a phone channel can be exercised on a clone
    with no subscribers registered. Ignored for area-addressed channels.

    Returns a per-recipient breakdown; never raises for a single bad recipient, so one
    unusable phone number cannot stop the rest of the area from being notified.
    """
    rec = load_recommendation(area_id, event, lead)
    provider = P.provider_for(channel)
    if channel in P.AREA_ADDRESSED:
        # One message serves everyone in the area, so the area id IS the address — no
        # subscriber list, no phone number, and nothing to validate against one.
        subs = [{"destination": area_id, "area_id": area_id, "channel": channel,
                 "lang": "kn", "name": None, "crop": None}]
    elif to:
        subs = [{"destination": to.strip(), "area_id": area_id, "channel": channel,
                 "lang": "kn", "name": None, "crop": None}]
        triggered_by = f"{triggered_by}-test"
    else:
        subs = SB.fetch_subscribers(channel=channel, area_id=area_id)
    if not subs:
        return {"area_id": area_id, "channel": channel, "provider": provider.label,
                "simulated": provider.simulated, "sent": 0, "failed": 0, "skipped": 0,
                "backend": None, "results": [],
                "note": "no active subscribers for this area on this channel"}

    already = set() if force else _recent_signatures(area_id)
    results, backend = [], None

    for s in subs:
        dest = (s.get("destination") or "").strip()
        bad = validate(s)
        if bad:
            results.append({"destination_masked": mask(dest), "farmer_name": s.get("name"),
                            "status": "invalid", "error": bad})
            continue
        if (channel, dest, rec["rule_id"]) in already:
            results.append({"destination_masked": mask(dest), "farmer_name": s.get("name"),
                            "status": "duplicate",
                            "error": f"same advice already sent within {DUPLICATE_WINDOW_HOURS}h"})
            continue

        # The channel decides its own rendering — SMS gets the *bold* markers stripped.
        # Recorded as sent, not as composed, so the log shows what actually went out.
        text = P.compose_for(provider, rec["message"])
        r = provider.send(dest, text, **({"meta": rec} if channel in P.AREA_ADDRESSED else {}))
        row, backend = ST.record({
            **rec,
            "message": text,
            "farmer_name": s.get("name"),
            "destination": dest,
            "crop": s.get("crop") or rec.get("crop"),
            "lang": s.get("lang", "kn"),
            "channel": channel,
            "provider": provider.label,
            "simulated": provider.simulated,
            "status": "sent" if r.ok else "failed",
            "provider_message_id": r.provider_message_id,
            "error": r.error,
            "sent_at": datetime.now(timezone.utc).isoformat() if r.ok else None,
            "triggered_by": triggered_by,
        })
        results.append({"id": row.get("id"), "destination_masked": mask(dest),
                        "farmer_name": s.get("name"), "status": row["status"],
                        "simulated": provider.simulated,
                        "provider_message_id": r.provider_message_id, "error": r.error})
        already.add((channel, dest, rec["rule_id"]))  # no double-send inside one request

    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("sent", "failed")}
    return {"area_id": area_id, "area_name": rec["area_name"], "channel": channel,
            "provider": provider.label, "simulated": provider.simulated,
            "rule_id": rec["rule_id"], "severity": rec["severity"], "risk_p": rec["risk_p"],
            "sent": counts["sent"], "failed": counts["failed"],
            "skipped": sum(1 for r in results if r["status"] in ("invalid", "duplicate")),
            "backend": backend, "results": results}


def history(area_id: str | None = None, limit: int = 100) -> dict:
    """The console's log view. Destinations are masked on the way out, always."""
    rows, backend = ST.recent(area_id=area_id, limit=limit)
    out = []
    for r in rows:
        r = dict(r)
        r["destination_masked"] = mask(r.pop("destination", ""))
        out.append(r)
    return {"backend": backend, "notifications": out}
