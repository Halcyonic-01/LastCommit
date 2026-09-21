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
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8787
AREA_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")  # also doubles as a path-traversal guard

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "services"))
from varshadrishti.data import supabase_client as SB  # noqa: E402
from advisory_text import compose  # noqa: E402
from notify import dispatcher as ND  # noqa: E402
from notify import providers as NP  # noqa: E402
from notify import store as NS  # noqa: E402


def _load_channel(name: str, path: Path):
    """services/*/send.py all share the basename 'send' — a plain `import send` for
    each would collide in sys.modules. Loading each by file path under a distinct
    name sidesteps that."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    """What /api/broadcast can reach. The notification console reads
    /api/notification-channels instead, which also reports simulation."""
    return {ch: NP.provider_for(ch).configured() for ch in NP.CHANNELS}


def run_broadcast(area_ids: list, event: str, lead: str, channels: list) -> dict:
    """Every queued area x every chosen channel, through the one dispatcher.

    This used to hold its own per-channel send loop beside services/notify/. Two send
    paths meant two places for a channel to drift, so the button and the console now
    share one: the dispatcher validates, suppresses duplicates, and records every
    message, whichever surface asked for it.
    """
    results = []
    for area_id in area_ids:
        for channel in channels:
            try:
                r = ND.dispatch(area_id, channel, event=event, lead=lead,
                                triggered_by="officer-dashboard")
            except ND.DispatchError as exc:
                results.append({"area_id": area_id, "channel": channel, "error": str(exc)})
                continue
            # Surface why, not just that it failed — an officer who is told "1 failed"
            # and nothing else has no way to act on it.
            reason = next((x["error"] for x in r.get("results", []) if x.get("error")), None)
            results.append({"area_id": area_id, "channel": channel, "ok": r["sent"],
                            "failed": r["failed"], "skipped": r["skipped"],
                            "simulated": r["simulated"], "error": reason or r.get("note")})
            # Best-effort — a failed log must never undo a send that already went out.
            if r["sent"]:
                SB.log_broadcast(area_ids=[area_id], event=event, lead=lead, channel=channel,
                                 recipient_count=r["sent"], triggered_by="officer-dashboard")

    return {"sent": sum(r.get("ok", 0) for r in results),
            "failed": sum(r.get("failed", 0) for r in results),
            "results": results}



class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Officer-Token")

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _params(self) -> dict:
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        return {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}

    def _authed(self) -> bool:
        """GET equivalent of the POST body token. Notification history carries a
        farmer's name and their advice — aggregate-only endpoints stay open, this
        does not."""
        return bool(TOKEN) and self.headers.get("X-Officer-Token") == TOKEN

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
            area_id = self._params().get("areaId", "")
            if not AREA_ID_RE.match(area_id):
                return self._json(400, {"error": "invalid or missing areaId"})
            area_file = ROOT / "forecast" / "area" / f"{area_id}.json"
            if not area_file.exists():
                return self._json(404, {"error": "no forecast file for this area"})
            return self._json(200, {"text": compose(area_file)})

        # Which provider each channel actually resolves to right now. No PII, and it is
        # what the console reads to label WhatsApp as simulated before anyone sends.
        # The farmer's own read. No passcode and no PII — exactly the trust level the
        # anon-readable farmer_messages table has, so the PWA can fall back to it.
        if self.path.startswith("/api/farmer-messages"):
            area_id = self._params().get("areaId", "")
            if not AREA_ID_RE.match(area_id):
                return self._json(400, {"error": "invalid or missing areaId"})
            rows, backend = NS.messages_for(area_id, limit=30)
            return self._json(200, {"backend": backend, "messages": rows})

        if self.path == "/api/notification-channels":
            return self._json(200, {"channels": NP.channel_status(),
                                    "duplicate_window_hours": ND.DUPLICATE_WINDOW_HOURS})

        if self.path.startswith("/api/notifications"):
            if not self._authed():
                return self._json(401, {"error": "missing or wrong X-Officer-Token"})
            q = self._params()
            try:
                limit = min(500, max(1, int(q.get("limit", 100))))
            except ValueError:
                return self._json(400, {"error": "limit must be a number"})
            area_id = q.get("areaId") or None
            if area_id and not AREA_ID_RE.match(area_id):
                return self._json(400, {"error": "invalid areaId"})
            return self._json(200, ND.history(area_id=area_id, limit=limit))

        if self.path.startswith("/api/notification-audience"):
            if not self._authed():
                return self._json(401, {"error": "missing or wrong X-Officer-Token"})
            q = self._params()
            area_id, channel = q.get("areaId", ""), q.get("channel", "")
            if not AREA_ID_RE.match(area_id):
                return self._json(400, {"error": "invalid or missing areaId"})
            if channel not in NP.CHANNELS:
                return self._json(400, {"error": f"channel must be one of {list(NP.CHANNELS)}"})
            return self._json(200, {"audience": ND.audience(area_id, channel)})

        return self._json(404, {"error": "not found"})

    def _body(self):
        """-> (parsed body, error response already sent?). Token checked here too."""
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "malformed JSON body"})
            return None
        if not TOKEN:
            self._json(401, {"error": "OFFICER_BROADCAST_TOKEN not set on the server — see .env.example"})
            return None
        if body.get("token") != TOKEN:
            self._json(401, {"error": "wrong token"})
            return None
        return body

    def do_POST(self):
        if self.path not in ("/api/broadcast", "/api/notify", "/api/notification-status"):
            return self._json(404, {"error": "not found"})

        body = self._body()
        if body is None:
            return None  # _body already sent the 400/401

        if self.path == "/api/broadcast":
            area_ids = body.get("areaIds") or []
            event, lead, channels = body.get("event"), body.get("lead"), body.get("channels") or []
            if not area_ids or not event or not lead or not channels:
                return self._json(400, {"error": "areaIds, event, lead and channels are all required"})
            return self._json(200, run_broadcast(area_ids, event, lead, channels))

        # The console's "Send Alert": one area, one channel, one record per recipient.
        if self.path == "/api/notify":
            channel = body.get("channel", "")
            if channel not in NP.CHANNELS:
                return self._json(400, {"error": f"channel must be one of {list(NP.CHANNELS)}"})
            try:
                return self._json(200, ND.dispatch(
                    body.get("areaId", ""), channel,
                    event=body.get("event", "p_dry7"), lead=body.get("lead", "w1"),
                    force=bool(body.get("force")), to=body.get("to") or None,
                ))
            except ND.DispatchError as exc:
                return self._json(400, {"error": str(exc)})

        # Where a real WhatsApp Cloud API delivery webhook would land (.env.example's
        # WHATSAPP_VERIFY_TOKEN). Nothing in this tree fabricates a delivery receipt.
        status, nid = body.get("status", ""), body.get("id", "")
        if status not in NS.STATUSES:
            return self._json(400, {"error": f"status must be one of {list(NS.STATUSES)}"})
        if not nid:
            return self._json(400, {"error": "id is required"})
        existing = NS.get(nid)
        if existing is None:
            return self._json(404, {"error": "no notification with that id"})
        refused = NS.refuse_reason(existing, status)
        if refused:
            return self._json(409, {"error": refused})
        row, backend = NS.set_status(nid, status, body.get("detail"))
        if row is None:
            return self._json(404, {"error": "no notification with that id", "backend": backend})
        row = dict(row)
        row["destination_masked"] = ND.mask(row.pop("destination", ""))
        return self._json(200, {"backend": backend, "notification": row})

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
