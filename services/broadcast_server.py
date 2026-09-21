"""Local backend for the officer dashboard's "Review broadcast" button.

The frontend is a static site with no backend of its own (Vercel isn't linked yet —
see IMPLEMENTATION_PLAN.md), and the real senders need secrets — bot tokens,
Supabase's service key — that must never reach the browser. This process
is that boundary: run it on the officer's own machine alongside `npm run dev`, and
the browser only ever holds a shared passcode.

    .venv/bin/python services/broadcast_server.py            # localhost:8787

Not a production backend — it's the same trust model as running services/*/send.py
from a terminal, just reachable from the dashboard instead of the command line. The
Vercel function this should become once the site is actually deployed can reuse the
same send_one()/compose() below almost unchanged.
"""

import importlib.util
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8787
AREA_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")  # also doubles as a path-traversal guard

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "services"))
from varshadrishti.data import supabase_client as SB  # noqa: E402
from advisory_text import compose  # noqa: E402


def _load_channel(name: str, path: Path):
    """telegram/send.py and whatsapp/send.py share the basename 'send' —
    a plain `import send` for each would collide in sys.modules. Loading
    each by its file path under a distinct name sidesteps that."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TG = _load_channel("broadcast_telegram", ROOT / "services" / "telegram" / "send.py")
WA = _load_channel("broadcast_whatsapp", ROOT / "services" / "whatsapp" / "send.py")


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
TOKEN = os.environ.get("OFFICER_BROADCAST_TOKEN", "").strip()


def configured_channels() -> dict:
    return {
        "telegram": bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()),
        "whatsapp": bool(os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
                         and os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()),
    }


def send_one(channel: str, area_id: str, text: str) -> dict:
    """-> {ok, failed, error}. Never raises — one bad channel or missing credential
    must not stop the other channels/areas in the same broadcast."""
    subs = SB.fetch_subscribers(channel=channel, area_id=area_id)
    if not subs:
        return {"ok": 0, "failed": 0, "error": None}

    if channel == "telegram":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            return {"ok": 0, "failed": len(subs), "error": "TELEGRAM_BOT_TOKEN not set"}
        ok = 0
        for s in subs:
            r = TG.call(token, "sendMessage", chat_id=s["destination"], text=text, parse_mode="Markdown")
            ok += 1 if r.get("ok") else 0
        return {"ok": ok, "failed": len(subs) - ok, "error": None}

    if channel == "whatsapp":
        phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
        if not phone_id or not token:
            return {"ok": 0, "failed": len(subs), "error": "WHATSAPP_PHONE_NUMBER_ID/WHATSAPP_ACCESS_TOKEN not set"}
        ok = 0
        for s in subs:
            payload = {"messaging_product": "whatsapp", "to": s["destination"], "type": "text",
                      "text": {"body": text, "preview_url": False}}
            r = WA.call(phone_id, token, payload)
            ok += 1 if r.get("messages") else 0
        return {"ok": ok, "failed": len(subs) - ok, "error": None}

    return {"ok": 0, "failed": 0, "error": f"unknown channel {channel!r}"}


def run_broadcast(area_ids: list, event: str, lead: str, channels: list) -> dict:
    results = []
    for area_id in area_ids:
        if not AREA_ID_RE.match(area_id):
            results.append({"area_id": area_id, "error": "invalid area id"})
            continue
        area_file = ROOT / "forecast" / "area" / f"{area_id}.json"
        if not area_file.exists():
            results.append({"area_id": area_id, "error": "no forecast file for this area"})
            continue
        text = compose(area_file)
        for channel in channels:
            r = send_one(channel, area_id, text)
            results.append({"area_id": area_id, "channel": channel, **r})
            # Best-effort — a failed log must never undo a send that already went out.
            if r.get("ok", 0) > 0:
                SB.log_broadcast(area_ids=[area_id], event=event, lead=lead, channel=channel,
                                 recipient_count=r["ok"], triggered_by="officer-dashboard")

    return {"sent": sum(r.get("ok", 0) for r in results),
            "failed": sum(r.get("failed", 0) for r in results),
            "results": results}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/health":
            return self._json(200, {"ok": True, "token_set": bool(TOKEN), "configured": configured_channels()})
        if self.path == "/api/subscriber-counts":
            # Aggregate counts only, never destinations — this is what lets the officer
            # table show "N subscribers" without needing the passcode just to look.
            counts: dict = {}
            for s in SB.fetch_subscribers():
                counts[s["area_id"]] = counts.get(s["area_id"], 0) + 1
            return self._json(200, counts)
        if self.path.startswith("/api/preview"):
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            area_id = params.get("areaId", "")
            if not AREA_ID_RE.match(area_id):
                return self._json(400, {"error": "invalid or missing areaId"})
            area_file = ROOT / "forecast" / "area" / f"{area_id}.json"
            if not area_file.exists():
                return self._json(404, {"error": "no forecast file for this area"})
            return self._json(200, {"text": compose(area_file)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/broadcast":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "malformed JSON body"})

        if not TOKEN:
            return self._json(401, {"error": "OFFICER_BROADCAST_TOKEN not set on the server — see .env.example"})
        if body.get("token") != TOKEN:
            return self._json(401, {"error": "wrong token"})

        area_ids = body.get("areaIds") or []
        event, lead, channels = body.get("event"), body.get("lead"), body.get("channels") or []
        if not area_ids or not event or not lead or not channels:
            return self._json(400, {"error": "areaIds, event, lead and channels are all required"})

        return self._json(200, run_broadcast(area_ids, event, lead, channels))

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[broadcast_server] {self.address_string()} {fmt % args}\n")


def main():
    if not TOKEN:
        print("WARNING: OFFICER_BROADCAST_TOKEN is not set in .env — every broadcast request will be "
              "rejected with 401 until it is. See .env.example.")
    print(f"broadcast server on http://localhost:{PORT}  (configured: {configured_channels()})")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
