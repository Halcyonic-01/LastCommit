"""Where a notification record lives: Supabase if it can take it, a local file if not.

No new database. Supabase is the project's store (schema/supabase.sql gained a
`notifications` table alongside subscribers/rain_reports/broadcasts), and the local
JSONL fallback keeps the officer's own dispatch log readable when Supabase is briefly
unreachable, so a send is never silently unrecorded. Every read reports which backend
answered, rather than leaving an operator guessing why history looks empty.

Note this is the officer-side log only. The farmer's copy lives in `farmer_messages`
and genuinely needs Supabase — a file on the officer's laptop cannot reach a phone.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "data" / "interim" / "notifications.jsonl"  # gitignored: holds destinations

sys.path.insert(0, str(ROOT / "src"))
from varshadrishti.data import supabase_client as SB  # noqa: E402

# Delivery lifecycle. `simulated` is a separate boolean on the row, never a status —
# a simulated send stops at "sent", and set_status() refuses to move it past that,
# because only a real provider webhook can honestly report a delivery.
STATUSES = ("queued", "sent", "delivered", "read", "failed")
# Only a real provider can report these. A simulated message was never transmitted, so
# there is nothing that could have delivered or read it — see refuse_reason().
REAL_DELIVERY_ONLY = ("delivered", "read")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_local() -> list[dict]:
    if not LOCAL.exists():
        return []
    rows = []
    for line in LOCAL.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a half-written line must not lose the rest of the history
    return rows


def _line(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False) + "\n"


def _append_local(row: dict) -> None:
    """Append-only, so a new record cannot rewrite or truncate the existing log."""
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL.open("a", encoding="utf-8") as fh:
        fh.write(_line(row))


def _rewrite_local(rows: list[dict]) -> None:
    """Only for an in-place status change — every other write appends."""
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LOCAL.write_text("".join(_line(r) for r in rows), encoding="utf-8")


def record(row: dict) -> tuple[dict, str]:
    """Persist one notification. -> (stored row, backend that took it)."""
    row = {"created_at": _now(), **row}
    stored = SB.insert_notification(row)
    if stored is not None:
        return stored, "supabase"
    row = {"id": str(uuid.uuid4()), **row}
    _append_local(row)
    return row, "file"


def recent(area_id: str | None = None, limit: int = 100) -> tuple[list[dict], str]:
    """Newest first. -> (rows, backend that answered)."""
    rows = SB.fetch_notifications(area_id=area_id, limit=limit)
    if rows is not None:
        return rows, "supabase"
    rows = [r for r in _read_local() if not area_id or r.get("area_id") == area_id]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows[:limit], "file"


def get(notification_id: str) -> dict | None:
    """One notification by id, from whichever backend holds it."""
    row = SB.fetch_notification(notification_id)
    if row is not None:
        return row or None
    return next((r for r in _read_local() if r.get("id") == notification_id), None)


def refuse_reason(row: dict, status: str) -> str | None:
    """-> why this status must not be applied to this row, or None if it may be."""
    if row.get("simulated") and status in REAL_DELIVERY_ONLY:
        return (f"this message was simulated and never transmitted — it cannot be marked "
                f"{status}; only a real provider's receipt can do that")
    return None


def set_status(notification_id: str, status: str, detail: str | None = None) -> tuple[dict | None, str]:
    """Advance one notification's delivery status. -> (updated row or None, backend).

    Refuses outright to mark a simulated message delivered/read — defence in depth behind
    the endpoint's own check, so a script cannot write the claim either.
    """
    row = get(notification_id)
    if row is not None and refuse_reason(row, status):
        return None, "refused"
    patch = {"status": status}
    if status in ("sent", "delivered", "read"):
        patch["sent_at"] = _now()
    if detail is not None:
        patch["error"] = detail
    updated = SB.update_notification(notification_id, patch)
    # {} means Supabase answered and held no such id — a real 404, not a reason to
    # go looking in the file store and report the wrong backend.
    if updated == {}:
        return None, "supabase"
    if updated is not None:
        return updated, "supabase"
    rows = _read_local()
    hit = None
    for r in rows:
        if r.get("id") == notification_id:
            r.update(patch)
            hit = r
    if hit is not None:
        _rewrite_local(rows)
    return hit, "file"
