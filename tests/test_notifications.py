"""Tests for the notification layer: providers, dispatcher, store, and its endpoints.

Nothing here is allowed to send a real message or touch the real Supabase project —
every test either forces the simulated provider or stubs the subscriber lookup, and
the record store is redirected to a tmp file. The recommendation, though, is real: it
comes out of the same forecast/area/*.json the app serves.
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

from notify import dispatcher as ND  # noqa: E402
from notify import providers as NP  # noqa: E402
from notify import store as NS  # noqa: E402

REAL_AREA = "KGIS-T-0101"  # Chikkodi block — same real area the broadcast tests use
FAKE_TOKEN = "fake-broadcast-token"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Every test writes to its own file and never reaches the real notifications table."""
    monkeypatch.setattr(NS, "LOCAL", tmp_path / "notifications.jsonl")
    # A hard floor: with no client, every supabase_client function degrades locally,
    # so a test that forgets to stub something still cannot reach the real project.
    monkeypatch.setattr(NS.SB, "client", lambda: None)
    monkeypatch.setattr(NS.SB, "insert_notification", lambda row: None)
    monkeypatch.setattr(NS.SB, "fetch_notifications", lambda area_id=None, limit=100: None)
    monkeypatch.setattr(NS.SB, "update_notification", lambda nid, patch: None)
    monkeypatch.setattr(NS.SB, "fetch_notification", lambda nid: None)
    monkeypatch.setattr(NP.SB, "insert_farmer_message", lambda row: {"id": "fm-stub", **row})


@pytest.fixture
def one_subscriber(monkeypatch):
    monkeypatch.setattr(ND.SB, "fetch_subscribers", lambda channel=None, area_id=None: [
        {"destination": "+919876500001", "area_id": REAL_AREA, "channel": channel,
         "lang": "kn", "name": "Test Farmer", "crop": "ragi"},
    ])


# --- providers ----------------------------------------------------------------

def test_whatsapp_is_simulated_until_the_meta_credentials_exist(monkeypatch):
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    p = NP.provider_for("whatsapp")
    assert isinstance(p, NP.SimulatedWhatsApp) and p.simulated is True


def test_setting_the_meta_credentials_is_the_only_switch_needed(monkeypatch):
    """The plug-in point: no code change turns the real Cloud API on."""
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "id")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
    p = NP.provider_for("whatsapp")
    assert isinstance(p, NP.WhatsAppCloud) and p.simulated is False


def test_a_simulated_send_can_never_look_like_a_real_one():
    r = NP.SimulatedWhatsApp().send("+919876500001", "text")
    assert r.ok and r.simulated is True
    assert r.provider_message_id.startswith("sim-"), "a simulated id must not pass for a Meta wamid"


def test_simulated_send_still_rejects_an_empty_destination():
    assert NP.SimulatedWhatsApp().send("", "text").ok is False


def test_sms_is_simulated_too_since_every_indian_gateway_is_metered():
    p = NP.provider_for("sms")
    assert p.simulated is True and p.label == "SMS (simulated)"


def test_sms_strips_the_markup_telegram_and_whatsapp_render():
    """A literal *ಮಳೆ* on a plain handset reads as broken text, not as bold."""
    assert NP.compose_for(NP.provider_for("sms"), "*bold* and _italic_ and normal") == \
        "bold and italic and normal"


def test_the_richer_channels_keep_their_markup():
    for channel in ("whatsapp", "telegram"):
        assert NP.compose_for(NP.provider_for(channel), "*bold*") == "*bold*"


def test_the_farmer_app_is_the_one_channel_that_really_delivers():
    p = NP.provider_for("inapp")
    assert p.simulated is False and p.label == "Farmer app"
    assert "inapp" in NP.AREA_ADDRESSED, "an in-app message is addressed by area, not by phone"


def test_an_inapp_send_writes_one_area_message_carrying_its_citation(monkeypatch):
    written = []
    monkeypatch.setattr(NP.SB, "insert_farmer_message",
                        lambda row: written.append(row) or {"id": "fm-1", **row})
    r = ND.dispatch(REAL_AREA, "inapp")
    assert r["sent"] == 1 and r["simulated"] is False
    assert len(written) == 1, "one message per area, not one per subscriber"
    assert written[0]["area_id"] == REAL_AREA
    assert written[0]["body"] and written[0]["rule_id"] and written[0]["source_table"]


def test_an_inapp_send_needs_no_subscribers_at_all(monkeypatch):
    monkeypatch.setattr(ND.SB, "fetch_subscribers",
                        lambda channel=None, area_id=None: pytest.fail("must not be consulted"))
    monkeypatch.setattr(NP.SB, "insert_farmer_message", lambda row: {"id": "fm-1", **row})
    assert ND.dispatch(REAL_AREA, "inapp")["sent"] == 1


def test_an_inapp_send_fails_readably_when_supabase_cannot_take_it(monkeypatch):
    monkeypatch.setattr(NP.SB, "insert_farmer_message", lambda row: None)
    r = ND.dispatch(REAL_AREA, "inapp")
    assert r["sent"] == 0 and r["failed"] == 1
    assert "supabase.sql" in r["results"][0]["error"].lower()


def test_a_channel_with_no_provider_at_all_fails_honestly():
    r = NP.Unsupported("pigeon").send("+919876500001", "text")
    assert r.ok is False and "no sender implemented" in r.error


def test_an_sms_notification_records_the_plain_text_that_actually_went_out(monkeypatch):
    monkeypatch.setattr(ND.SB, "fetch_subscribers", lambda channel=None, area_id=None: [
        {"destination": "+919876500001", "area_id": REAL_AREA, "channel": "sms", "lang": "kn"}])
    assert ND.dispatch(REAL_AREA, "sms")["sent"] == 1
    assert "*" not in NS.recent()[0][0]["message"], "the stored SMS kept markup it never sent"


# --- the recommendation this layer carries ------------------------------------

def test_load_recommendation_reads_the_real_rules_engine_output():
    rec = ND.load_recommendation(REAL_AREA)
    assert rec["rule_id"] and rec["recommendation_en"] and rec["recommendation_kn"]
    assert rec["source_table"], "a CRIDA citation must travel with the advice"
    assert 0.0 <= rec["risk_p"] <= 1.0
    assert rec["message"], "the dispatched text is the same compose() every channel uses"


def test_load_recommendation_rejects_a_path_traversal_area_id():
    with pytest.raises(ND.DispatchError, match="invalid area id"):
        ND.load_recommendation("../../etc/passwd")


def test_load_recommendation_rejects_an_unknown_area():
    with pytest.raises(ND.DispatchError, match="no forecast file"):
        ND.load_recommendation("KGIS-T-NOPE")


@pytest.mark.parametrize("event,lead", [("p_rainbow", "w1"), ("p_dry7", "w9")])
def test_load_recommendation_rejects_an_unknown_event_or_lead(event, lead):
    with pytest.raises(ND.DispatchError):
        ND.load_recommendation(REAL_AREA, event, lead)


# --- validation and masking ---------------------------------------------------

@pytest.mark.parametrize("dest,bad", [
    ("+919876500001", False), ("919876500001", False), ("", True),
    ("not-a-phone", True), ("12", True),
])
def test_validate_catches_unusable_farmer_data(dest, bad):
    sub = {"destination": dest, "channel": "whatsapp", "area_id": REAL_AREA}
    assert (ND.validate(sub) is not None) is bad


def test_a_telegram_chat_id_is_not_held_to_the_phone_number_rule():
    assert ND.validate({"destination": "8414993", "channel": "telegram", "area_id": REAL_AREA}) is None


def test_mask_never_returns_a_whole_destination():
    assert ND.mask("+919876500001") == "+91***01"
    assert ND.mask("123") == "***"


# --- dispatch -----------------------------------------------------------------

def test_dispatch_sends_records_and_reports_that_it_was_simulated(monkeypatch, one_subscriber):
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    r = ND.dispatch(REAL_AREA, "whatsapp")
    assert r["sent"] == 1 and r["failed"] == 0
    assert r["simulated"] is True and r["provider"] == "WhatsApp (simulated)"
    assert r["results"][0]["status"] == "sent"
    stored = NS.recent()[0]
    assert len(stored) == 1 and stored[0]["simulated"] is True
    assert stored[0]["status"] == "sent", "a simulation must stop at sent, never claim delivery"


def test_a_recorded_notification_carries_the_advice_and_its_citation(one_subscriber):
    ND.dispatch(REAL_AREA, "whatsapp")
    row = NS.recent()[0][0]
    for key in ("area_name", "district", "severity", "risk_event", "risk_p", "rule_id",
                "recommendation_en", "recommendation_kn", "source_table", "message"):
        assert row.get(key) not in (None, ""), f"{key} missing from the stored notification"
    assert row["farmer_name"] == "Test Farmer" and row["crop"] == "ragi"


def test_the_same_advice_is_not_sent_twice_inside_the_window(one_subscriber):
    assert ND.dispatch(REAL_AREA, "whatsapp")["sent"] == 1
    again = ND.dispatch(REAL_AREA, "whatsapp")
    assert again["sent"] == 0 and again["skipped"] == 1
    assert again["results"][0]["status"] == "duplicate"


def test_force_overrides_the_duplicate_guard(one_subscriber):
    ND.dispatch(REAL_AREA, "whatsapp")
    assert ND.dispatch(REAL_AREA, "whatsapp", force=True)["sent"] == 1


def test_a_failed_attempt_is_not_treated_as_a_duplicate(one_subscriber, monkeypatch):
    """Resending after a failure is the whole point — it must not be suppressed."""
    failing = [True]  # flipped rather than monkeypatch.undo(), which would also undo the store isolation
    monkeypatch.setattr(NP.SimulatedWhatsApp, "send", lambda self, d, t: NP.Result(
        ok=not failing[0], simulated=True,
        error="boom" if failing[0] else None,
        provider_message_id=None if failing[0] else "sim-deadbeef"))
    assert ND.dispatch(REAL_AREA, "whatsapp")["failed"] == 1
    failing[0] = False
    assert ND.dispatch(REAL_AREA, "whatsapp")["sent"] == 1


def test_one_unusable_number_does_not_stop_the_rest(monkeypatch):
    monkeypatch.setattr(ND.SB, "fetch_subscribers", lambda channel=None, area_id=None: [
        {"destination": "nonsense", "area_id": REAL_AREA, "channel": "whatsapp", "lang": "kn"},
        {"destination": "+919876500002", "area_id": REAL_AREA, "channel": "whatsapp", "lang": "kn"},
    ])
    r = ND.dispatch(REAL_AREA, "whatsapp")
    assert r["sent"] == 1 and r["skipped"] == 1
    assert [x["status"] for x in r["results"]] == ["invalid", "sent"]


def test_an_area_with_no_subscribers_says_so_instead_of_failing(monkeypatch):
    monkeypatch.setattr(ND.SB, "fetch_subscribers", lambda channel=None, area_id=None: [])
    r = ND.dispatch(REAL_AREA, "whatsapp")
    assert r["sent"] == 0 and "no active subscribers" in r["note"]


def test_the_test_recipient_override_bypasses_the_subscriber_list(monkeypatch):
    monkeypatch.setattr(ND.SB, "fetch_subscribers",
                        lambda channel=None, area_id=None: pytest.fail("must not be consulted"))
    r = ND.dispatch(REAL_AREA, "whatsapp", to="+919876500009")
    assert r["sent"] == 1
    assert NS.recent()[0][0]["triggered_by"].endswith("-test")


def test_history_masks_every_destination(one_subscriber):
    ND.dispatch(REAL_AREA, "whatsapp")
    h = ND.history()
    assert h["notifications"], "nothing recorded"
    for n in h["notifications"]:
        assert "destination" not in n, "a raw phone number escaped into the history payload"
        assert n["destination_masked"].count("*") == 3
    assert "9876500001" not in json.dumps(h)


# --- the store ----------------------------------------------------------------

def test_the_store_falls_back_to_a_file_and_says_which_backend_answered(one_subscriber):
    row, backend = NS.record({"area_id": REAL_AREA, "channel": "whatsapp", "status": "queued",
                              "destination": "+919876500001", "provider": "x", "simulated": True})
    assert backend == "file" and row["id"]
    rows, backend = NS.recent()
    assert backend == "file" and len(rows) == 1


def test_set_status_advances_a_real_notification_and_stamps_a_time(one_subscriber, monkeypatch):
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "id")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(NP.WhatsAppCloud, "send",
                        lambda self, d, t: NP.Result(ok=True, simulated=False, provider_message_id="wamid.1"))
    ND.dispatch(REAL_AREA, "whatsapp")
    nid = NS.recent()[0][0]["id"]
    row, backend = NS.set_status(nid, "delivered")
    assert row["status"] == "delivered" and row["sent_at"] and backend == "file"


@pytest.mark.parametrize("status", NS.REAL_DELIVERY_ONLY)
def test_a_simulated_message_can_never_be_marked_delivered(one_subscriber, status):
    """The one claim this whole layer exists to avoid making."""
    ND.dispatch(REAL_AREA, "whatsapp")
    row = NS.recent()[0][0]
    assert row["simulated"] is True
    assert NS.refuse_reason(row, status), "a simulated row must refuse a delivery receipt"
    assert NS.set_status(row["id"], status) == (None, "refused")
    assert NS.recent()[0][0]["status"] == "sent", "the stored status changed anyway"


def test_a_simulated_message_can_still_be_marked_failed(one_subscriber):
    """Refusing delivery receipts must not freeze the row — a failure is still reportable."""
    ND.dispatch(REAL_AREA, "whatsapp")
    nid = NS.recent()[0][0]["id"]
    assert NS.set_status(nid, "failed", "provider rejected it")[0]["status"] == "failed"


def test_set_status_on_an_unknown_id_reports_nothing_rather_than_inventing_a_row():
    assert NS.set_status("no-such-id", "delivered")[0] is None


# --- the HTTP endpoints -------------------------------------------------------

@pytest.fixture
def server(monkeypatch, isolated_store):
    import broadcast_server as BS
    monkeypatch.setattr(BS, "TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(BS.ND.SB, "fetch_subscribers", lambda channel=None, area_id=None: [
        {"destination": "+919876500001", "area_id": REAL_AREA, "channel": channel,
         "lang": "kn", "name": "Test Farmer", "crop": "ragi"},
    ])
    httpd = ThreadingHTTPServer(("localhost", 0), BS.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://localhost:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def _req(url, method="GET", payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_channel_status_is_public_and_names_the_simulated_provider(server, monkeypatch):
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    status, body = _req(f"{server}/api/notification-channels")
    assert status == 200
    assert body["channels"]["whatsapp"]["simulated"] is True
    assert body["duplicate_window_hours"] == ND.DUPLICATE_WINDOW_HOURS


def test_history_is_refused_without_the_officer_token(server):
    assert _req(f"{server}/api/notifications")[0] == 401


def test_history_is_returned_with_the_officer_token(server):
    status, body = _req(f"{server}/api/notifications", headers={"X-Officer-Token": FAKE_TOKEN})
    assert status == 200 and body["notifications"] == [] and body["backend"] == "file"


def test_audience_is_refused_without_the_officer_token(server):
    assert _req(f"{server}/api/notification-audience?areaId={REAL_AREA}&channel=whatsapp")[0] == 401


def test_audience_masks_the_destination(server):
    status, body = _req(f"{server}/api/notification-audience?areaId={REAL_AREA}&channel=whatsapp",
                        headers={"X-Officer-Token": FAKE_TOKEN})
    assert status == 200
    assert body["audience"][0]["destination_masked"] == "+91***01"
    assert "9876500001" not in json.dumps(body)


def test_audience_rejects_an_unknown_channel(server):
    status, _ = _req(f"{server}/api/notification-audience?areaId={REAL_AREA}&channel=pigeon",
                     headers={"X-Officer-Token": FAKE_TOKEN})
    assert status == 400


def test_notify_requires_the_token(server):
    assert _req(f"{server}/api/notify", "POST", {"areaId": REAL_AREA, "channel": "whatsapp"})[0] == 401


def test_notify_dispatches_and_reports_the_simulation(server, monkeypatch):
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    status, body = _req(f"{server}/api/notify", "POST",
                        {"token": FAKE_TOKEN, "areaId": REAL_AREA, "channel": "whatsapp"})
    assert status == 200
    assert body["sent"] == 1 and body["simulated"] is True
    assert "9876500001" not in json.dumps(body), "the notify response leaked a destination"


def test_notify_rejects_an_unknown_channel(server):
    status, _ = _req(f"{server}/api/notify", "POST",
                     {"token": FAKE_TOKEN, "areaId": REAL_AREA, "channel": "pigeon"})
    assert status == 400


def test_notify_rejects_a_bad_area_without_a_stack_trace(server):
    status, body = _req(f"{server}/api/notify", "POST",
                        {"token": FAKE_TOKEN, "areaId": "../../etc/passwd", "channel": "whatsapp"})
    assert status == 400 and "invalid area id" in body["error"]


def test_status_endpoint_rejects_an_unknown_status(server):
    status, _ = _req(f"{server}/api/notification-status", "POST",
                     {"token": FAKE_TOKEN, "id": "x", "status": "vibes"})
    assert status == 400


def test_status_endpoint_404s_on_an_unknown_id(server):
    status, _ = _req(f"{server}/api/notification-status", "POST",
                     {"token": FAKE_TOKEN, "id": "no-such-id", "status": "delivered"})
    assert status == 404


def test_the_status_endpoint_refuses_to_mark_a_simulated_message_delivered(server, monkeypatch):
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    _, sent = _req(f"{server}/api/notify", "POST",
                   {"token": FAKE_TOKEN, "areaId": REAL_AREA, "channel": "whatsapp"})
    status, body = _req(f"{server}/api/notification-status", "POST",
                        {"token": FAKE_TOKEN, "id": sent["results"][0]["id"], "status": "delivered"})
    assert status == 409 and "simulated" in body["error"]


def test_a_real_delivery_receipt_can_advance_a_recorded_notification(server, monkeypatch):
    """The shape a WhatsApp Cloud API webhook would post — the reason this endpoint exists."""
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "id")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(NP.WhatsAppCloud, "send",
                        lambda self, d, t: NP.Result(ok=True, simulated=False, provider_message_id="wamid.1"))
    _, sent = _req(f"{server}/api/notify", "POST",
                   {"token": FAKE_TOKEN, "areaId": REAL_AREA, "channel": "whatsapp"})
    nid = sent["results"][0]["id"]
    status, body = _req(f"{server}/api/notification-status", "POST",
                        {"token": FAKE_TOKEN, "id": nid, "status": "delivered"})
    assert status == 200 and body["notification"]["status"] == "delivered"
    assert "destination" not in body["notification"]


def test_the_existing_broadcast_endpoint_still_works(server):
    """The notification layer is additive — it must not disturb P9's broadcast path."""
    status, body = _req(f"{server}/api/broadcast", "POST",
                        {"token": FAKE_TOKEN, "areaIds": [REAL_AREA], "event": "p_dry7",
                         "lead": "w1", "channels": ["whatsapp"]})
    assert status == 200 and "results" in body
