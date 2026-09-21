"""Tests for services/broadcast_server.py — the officer dashboard's only backend.

The HTTP-level tests run the real server on an ephemeral port so the token check,
JSON error paths, and status codes are tested as real requests, not just direct
function calls. Only Supabase and the outbound provider calls are mocked — never a real send.
"""

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "services"))

import broadcast_server as BS  # noqa: E402

REAL_AREA = "KGIS-T-0101"  # Chikkodi block — confirmed present in forecast/area/
FAKE_TOKEN = "fake-broadcast-token"  # not a real secret, just a value the handler will accept


# --- run_broadcast(): every area x every channel, through the dispatcher ------------

def test_run_broadcast_delegates_to_the_dispatcher_and_logs_what_sent(monkeypatch):
    calls, logged = [], []
    monkeypatch.setattr(BS.ND, "dispatch", lambda area_id, channel, **kw: calls.append((area_id, channel)) or {
        "sent": 1 if channel == "inapp" else 0, "failed": 0, "skipped": 0,
        "simulated": channel != "inapp", "note": None})
    monkeypatch.setattr(BS.SB, "log_broadcast", lambda **kw: logged.append(kw) or True)

    result = BS.run_broadcast([REAL_AREA], "p_dry7", "w1", ["inapp", "whatsapp"])

    assert calls == [(REAL_AREA, "inapp"), (REAL_AREA, "whatsapp")]
    assert result["sent"] == 1 and result["failed"] == 0
    assert len(logged) == 1 and logged[0]["channel"] == "inapp"


def test_run_broadcast_reports_a_bad_area_without_raising(monkeypatch):
    monkeypatch.setattr(BS.SB, "log_broadcast", lambda **kw: True)
    result = BS.run_broadcast(["KGIS-T-DOES-NOT-EXIST"], "p_dry7", "w1", ["inapp"])
    assert result["results"][0]["error"] == "no forecast file for this area"


def test_run_broadcast_rejects_a_path_traversal_area_id(monkeypatch):
    """Area ids flow straight into a filesystem path — must not trust client input."""
    monkeypatch.setattr(BS.SB, "log_broadcast", lambda **kw: True)
    result = BS.run_broadcast(["../../etc/passwd"], "p_dry7", "w1", ["inapp"])
    assert result["results"][0]["error"] == "invalid area id"


# --- the HTTP server itself ---------------------------------------------------

@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setattr(BS, "TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(BS.SB, "fetch_subscribers", lambda channel=None, area_id=None: [])
    monkeypatch.setattr(BS.SB, "log_broadcast", lambda **kw: True)
    monkeypatch.setattr(BS.NS.SB, "client", lambda: None)  # never reach the real project
    monkeypatch.setattr(BS.NS, "LOCAL", tmp_path / "notifications.jsonl")
    httpd = ThreadingHTTPServer(("localhost", 0), BS.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://localhost:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def _get(base, path):
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(base, path, payload):
    req = urllib.request.Request(f"{base}{path}", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_health_reports_token_and_channel_configuration(server):
    status, body = _get(server, "/api/health")
    assert status == 200
    assert body["token_set"] is True
    assert set(body["configured"]) == set(BS.NP.CHANNELS)


def test_subscriber_counts_are_aggregated_never_raw_destinations(server, monkeypatch):
    monkeypatch.setattr(BS.SB, "fetch_subscribers", lambda channel=None, area_id=None: [
        {"area_id": "A", "destination": "111"}, {"area_id": "A", "destination": "222"},
        {"area_id": "B", "destination": "333"},
    ])
    status, body = _get(server, "/api/subscriber-counts")
    assert status == 200
    assert body == {"A": 2, "B": 1}
    assert "111" not in json.dumps(body), "a phone number/chat id leaked into the aggregate endpoint"


def test_broadcast_rejects_missing_token(server):
    status, body = _post(server, "/api/broadcast",
                         {"areaIds": [REAL_AREA], "event": "p_dry7", "lead": "w1", "channels": ["inapp"]})
    assert status == 401


def test_broadcast_rejects_wrong_token(server):
    status, body = _post(server, "/api/broadcast",
                         {"token": "wrong", "areaIds": [REAL_AREA], "event": "p_dry7", "lead": "w1", "channels": ["inapp"]})
    assert status == 401


def test_broadcast_rejects_incomplete_request(server):
    status, body = _post(server, "/api/broadcast", {"token": FAKE_TOKEN, "areaIds": []})
    assert status == 400


def test_broadcast_rejects_malformed_json(server):
    req = urllib.request.Request(f"{server}/api/broadcast", data=b"{not json", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 400


def test_broadcast_succeeds_with_the_right_token(server):
    status, body = _post(server, "/api/broadcast",
                         {"token": FAKE_TOKEN, "areaIds": [REAL_AREA], "event": "p_dry7", "lead": "w1",
                          "channels": ["whatsapp"]})
    assert status == 200
    assert body["sent"] == 0 and body["failed"] == 0  # fixture stubs zero subscribers — no crash either way


def test_preview_returns_the_real_composed_text(server):
    status, body = _get(server, f"/api/preview?areaId={REAL_AREA}")
    assert status == 200
    assert "%" in body["text"] and "bulletin" in body["text"]


def test_preview_rejects_invalid_area_id(server):
    status, body = _get(server, "/api/preview?areaId=../../etc/passwd")
    assert status == 400
