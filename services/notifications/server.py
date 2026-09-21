"""Minimal local API for the notification console.

Run with: python -m services.notifications.server
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .dispatcher import dispatch
from .store import list_notifications, update_notification


def send_json(handler, code, data):
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
    handler.end_headers()
    handler.wfile.write(raw)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def do_OPTIONS(self):
        send_json(self, 204, {})

    def do_GET(self):
        if urlparse(self.path).path == "/api/notifications":
            send_json(self, 200, {"notifications": list_notifications()})
        else:
            send_json(self, 404, {"error": "Not found"})

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self):
        if urlparse(self.path).path != "/api/notifications":
            send_json(self, 404, {"error": "Not found"})
            return
        try:
            record, duplicate = dispatch(self._body())
            send_json(self, 200 if duplicate else 201, {"notification": record, "duplicate": duplicate})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            send_json(self, 400, {"error": str(exc)})
        except Exception as exc:
            send_json(self, 500, {"error": f"Notification dispatch failed: {exc}"})

    def do_PATCH(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) != 3 or parts[:2] != ["api", "notifications"]:
            send_json(self, 404, {"error": "Not found"})
            return
        try:
            body = self._body()
            if body.get("status") not in {"queued", "simulated", "failed"}:
                raise ValueError("status must be queued, simulated, or failed")
            row = update_notification(parts[2], body["status"], body.get("detail", "Updated by operator"))
            send_json(self, 200 if row else 404, {"notification": row} if row else {"error": "Notification not found"})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            send_json(self, 400, {"error": str(exc)})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Notification API listening on http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
