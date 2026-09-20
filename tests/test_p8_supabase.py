"""Supabase integration: schema, env contract, and graceful degradation when unset.

Every python function here must return an empty/None/False result rather than raise
when Supabase isn't configured — a fresh clone with no .env has to keep working exactly
as it did before this integration existed.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SQL = (ROOT / "schema" / "supabase.sql").read_text()


def test_schema_defines_all_three_tables():
    for table in ("rain_reports", "subscribers", "broadcasts"):
        assert re.search(rf"create table if not exists {table}", SQL), f"{table} missing"


def test_schema_enables_row_level_security_on_all_three():
    assert SQL.count("enable row level security") == 3


def test_only_rain_reports_grants_anon_access():
    """subscribers (phone numbers) and broadcasts (audit log) must stay service-role only."""
    # each block runs from its own table's CREATE to the next table's
    rain_block = SQL[SQL.index("create table if not exists rain_reports"):
                     SQL.index("create table if not exists subscribers")]
    subs_block = SQL[SQL.index("create table if not exists subscribers"):
                     SQL.index("create table if not exists broadcasts")]
    bcast_block = SQL[SQL.index("create table if not exists broadcasts"):]

    assert "to anon" in rain_block
    assert "to anon" not in subs_block, "subscribers must not be anon-readable"
    assert "to anon" not in bcast_block, "broadcasts must not be anon-readable"


def test_env_example_documents_every_key():
    env = (ROOT / ".env.example").read_text()
    for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY",
               "VITE_SUPABASE_URL", "VITE_SUPABASE_ANON_KEY"):
        assert f"{key}=" in env, f"{key} not documented in .env.example"


@pytest.fixture
def unconfigured(monkeypatch, tmp_path):
    """No SUPABASE_* env, and no .env file to load one from — the fresh-clone state.

    Points supabase_client.ROOT at an empty temp dir rather than asserting the real
    .env is absent — this machine's has Telegram filled in and Supabase blank, and the
    test must stay correct (and never risk a live call) once Supabase gets filled in too.
    """
    from varshadrishti.data import supabase_client as SB

    for k in list(__import__("os").environ):
        if k.startswith("SUPABASE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(SB, "ROOT", tmp_path)


def test_client_is_none_when_unconfigured(unconfigured):
    from varshadrishti.data import supabase_client as SB

    assert SB.client() is None


def test_fetchers_degrade_to_empty_without_network(unconfigured):
    from varshadrishti.data import supabase_client as SB

    assert SB.fetch_subscribers() == []
    assert SB.fetch_subscribers(channel="telegram") == []
    assert SB.fetch_rain_reports() == []
    assert SB.log_broadcast(area_ids=["x"], event="p_dry7", lead="w1",
                            channel="telegram", recipient_count=0) is False
    assert SB.add_subscriber(area_id="x", channel="telegram", destination="1") is False


def test_telegram_setup_discovers_fresh_and_known_chats(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import telegram_setup as ts  # noqa: PLC0415

    # a fresh /start from someone new, via a faked getUpdates response
    fresh = {"ok": True, "result": [{"message": {"chat": {"id": 111, "first_name": "Farmer"}}}]}
    monkeypatch.setattr(ts, "call", lambda token, method, **p: fresh)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "8417182293")
    chats = ts.discover_chats("fake-token")
    assert chats == {111: "Farmer", 8417182293: "(from .env TELEGRAM_CHAT_ID)"}

    # getUpdates aged out (empty result) -> the known chat id is still folded in
    monkeypatch.setattr(ts, "call", lambda token, method, **p: {"ok": True, "result": []})
    assert ts.discover_chats("fake-token") == {8417182293: "(from .env TELEGRAM_CHAT_ID)"}

    # neither source has anything -> genuinely empty
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert ts.discover_chats("fake-token") == {}


def test_telegram_setup_registers_discovered_chats_as_subscribers(monkeypatch, unconfigured):
    """Runs the real main(), with only the network and Supabase calls faked."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import telegram_setup as ts  # noqa: PLC0415

    responses = {
        "getMe": {"ok": True, "result": {"username": "test_bot", "first_name": "Test"}},
        "getUpdates": {"ok": True, "result": [
            {"message": {"chat": {"id": 111, "first_name": "Farmer"}}},
        ]},
    }
    monkeypatch.setattr(ts, "call", lambda token, method, **p: responses[method])
    monkeypatch.setattr(ts, "load_env", lambda: "fake-token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    registered = []
    monkeypatch.setattr(ts.SB, "client", lambda: object())  # "configured", no real network
    monkeypatch.setattr(ts.SB, "add_subscriber", lambda **kw: registered.append(kw) or True)
    monkeypatch.setattr(sys, "argv", ["telegram_setup.py", "--area", "KGIS-H-999999", "--lang", "hi"])

    assert ts.main() == 0
    assert registered == [{"area_id": "KGIS-H-999999", "channel": "telegram",
                           "destination": "111", "lang": "hi"}]


def test_send_py_falls_back_through_the_documented_order(monkeypatch, unconfigured):
    sys.path.insert(0, str(ROOT / "services" / "telegram"))
    import send  # noqa: PLC0415

    # override wins regardless of everything else
    assert send.resolve_chats("explicit") == ["explicit"]

    # empty Supabase (unconfigured) + no env + no local file -> nothing
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(send, "SUBS", ROOT / "does" / "not" / "exist.json")
    assert send.resolve_chats(None) == []

    # env var used once Supabase has nothing to offer
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    assert send.resolve_chats(None) == ["12345"]

    # a populated Supabase subscriber list wins over the env var
    monkeypatch.setattr(send.SB, "fetch_subscribers",
                        lambda channel=None: [{"destination": "999"}])
    assert send.resolve_chats(None) == ["999"]


def test_web_supabase_client_degrades_to_null_when_unconfigured():
    js = (ROOT / "web" / "src" / "lib" / "supabase.js").read_text()
    assert "createClient" in js
    assert "null" in js, "must not construct a client with missing env vars"


def test_web_declares_the_dependency_and_reads_env_from_repo_root():
    pkg = (ROOT / "web" / "package.json").read_text()
    assert '"@supabase/supabase-js"' in pkg
    cfg = (ROOT / "web" / "vite.config.js").read_text()
    assert "envDir" in cfg, "VITE_SUPABASE_* must resolve from the root .env, not web/.env"


def test_rain_report_outbox_posts_to_supabase_not_a_generic_endpoint():
    store = (ROOT / "web" / "src" / "lib" / "store.js").read_text()
    assert "VITE_REPORT_ENDPOINT" not in store, "the generic-endpoint stub should be gone"
    assert 'from("rain_reports")' in store
    assert ".insert(" in store
