"""Supabase integration: schema, env contract, and graceful degradation when unset.

Every python function here must return an empty/None/False result rather than raise
when Supabase isn't configured — a fresh clone with no .env has to keep working exactly
as it did before this integration existed.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SQL = (ROOT / "schema" / "supabase.sql").read_text()


def _load(name: str, path: Path):
    """Load a module under an explicit name, bypassing sys.modules.

    Several services/*/send.py files share the basename
    'send' — a plain `import send` in two tests would silently return whichever
    one happened to be cached first. Loading each by its file path under a
    distinct name sidesteps that collision entirely.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TABLES = ("rain_reports", "subscribers", "broadcasts", "notifications", "farmer_messages")


def test_schema_defines_every_table():
    for table in TABLES:
        assert re.search(rf"create table if not exists {table}", SQL), f"{table} missing"


def test_schema_enables_row_level_security_on_every_table():
    assert SQL.count("enable row level security") == len(TABLES)


def _table_block(name: str) -> str:
    """Just this table's own section — the next `create table` ends it."""
    start = SQL.index(f"create table if not exists {name}")
    nxt = SQL.find("create table if not exists ", start + 1)
    return SQL[start:] if nxt == -1 else SQL[start:nxt]


@pytest.mark.parametrize("table", ["broadcasts", "notifications"])
def test_service_role_only_tables_grant_no_anon_access(table):
    """The send audit log and the per-farmer notification log both hold data anon
    must never see — a destination and a name, in notifications' case."""
    assert "to anon" not in _table_block(table), f"{table} must not be anon-readable"


def test_rain_reports_grants_anon_insert_and_select():
    rain_block = SQL[SQL.index("create table if not exists rain_reports"):
                     SQL.index("create table if not exists subscribers")]
    assert "to anon" in rain_block


def test_subscribers_anon_can_insert_but_never_read_the_list_back():
    """Onboarding lets a farmer add their own WhatsApp/SMS number and nothing more:
    no anon select, because the phone list must never be readable from a browser."""
    subs_block = SQL[SQL.index("create table if not exists subscribers"):
                     SQL.index("create table if not exists broadcasts")]
    assert "for insert to anon" in subs_block
    assert "for select to anon" not in subs_block, "the subscriber list must not be anon-readable"
    assert "'whatsapp', 'sms'" in subs_block, "anon may only register a phone channel"


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
    assert SB.fetch_subscribers(channel="whatsapp") == []
    assert SB.fetch_rain_reports() == []
    assert SB.log_broadcast(area_ids=["x"], event="p_dry7", lead="w1",
                            channel="whatsapp", recipient_count=0) is False
    assert SB.add_subscriber(area_id="x", channel="telegram", destination="1") is False


def test_env_example_documents_whatsapp_keys():
    env = (ROOT / ".env.example").read_text()
    for key in ("WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_TEST_RECIPIENT"):
        assert f"{key}=" in env, f"{key} not documented in .env.example"


def test_every_channel_composes_from_the_one_shared_advisory_text():
    """Pins the services/advisory_text.py extraction. The CLI WhatsApp sender and the
    dispatcher behind the officer console must not drift into different advice."""
    import sys as _sys  # noqa: PLC0415
    _sys.path.insert(0, str(ROOT / "services"))
    from notify import dispatcher as ND  # noqa: PLC0415
    wa_send = _load("wa_send_pin", ROOT / "services" / "whatsapp" / "send.py")
    assert wa_send.compose is ND.compose


def test_whatsapp_send_falls_back_through_the_documented_order(monkeypatch, unconfigured):
    send = _load("wa_send_order", ROOT / "services" / "whatsapp" / "send.py")

    # override wins regardless of everything else
    assert send.resolve_recipients("explicit") == ["explicit"]

    # empty Supabase (unconfigured) + no env -> nothing
    monkeypatch.delenv("WHATSAPP_TEST_RECIPIENT", raising=False)
    assert send.resolve_recipients(None) == []

    # env var used once Supabase has nothing to offer
    monkeypatch.setenv("WHATSAPP_TEST_RECIPIENT", "919999999999")
    assert send.resolve_recipients(None) == ["919999999999"]

    # a populated Supabase subscriber list wins over the env var
    monkeypatch.setattr(send.SB, "fetch_subscribers",
                        lambda channel=None: [{"destination": "918888888888"}])
    assert send.resolve_recipients(None) == ["918888888888"]


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


def test_farmer_messages_is_anon_readable_because_that_read_is_the_delivery():
    """The PWA has no login. If anon cannot select farmer_messages, nothing reaches a farmer."""
    block = _table_block("farmer_messages")
    assert "for select to anon" in block
    assert "for insert to anon" not in block, "only the officer's service role may send"
    for pii in ("destination", "farmer_name", "phone"):
        assert pii not in block, f"farmer_messages must hold no {pii}"
