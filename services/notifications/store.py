"""Small JSON store for this static-forecast project; no second database is needed."""

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "data" / "notifications.json"
_LOCK = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read():
    if not PATH.exists():
        return []
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write(rows):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="notifications-", suffix=".json", dir=PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def list_notifications(limit=100):
    with _LOCK:
        return sorted(_read(), key=lambda row: row["created_at"], reverse=True)[:limit]


def find_duplicate(idempotency_key):
    if not idempotency_key:
        return None
    return next((row for row in _read() if row.get("idempotency_key") == idempotency_key), None)


def create_notification(record):
    with _LOCK:
        duplicate = find_duplicate(record.get("idempotency_key"))
        if duplicate:
            return duplicate, True
        row = {
            **record,
            "id": str(uuid.uuid4()),
            "created_at": _now(),
            "updated_at": _now(),
            "status": record.get("status", "queued"),
            "history": [{"status": record.get("status", "queued"), "at": _now(), "detail": "Created"}],
        }
        rows = _read()
        rows.append(row)
        _write(rows)
        return row, False


def update_notification(notification_id, status, detail=""):
    with _LOCK:
        rows = _read()
        for row in rows:
            if row["id"] == notification_id:
                row["status"] = status
                row["updated_at"] = _now()
                row.setdefault("history", []).append({"status": status, "at": row["updated_at"], "detail": detail})
                _write(rows)
                return row
    return None
