"""Send today's advisory to SMS subscribers via Twilio.

SMS has no rich text — Telegram/WhatsApp's *bold*/_italic_ markers would show as
literal asterisks and underscores on a plain phone, so those are stripped before
sending. Kannada forces UCS-2 encoding (67 chars/segment, not the GSM-7 160), so
the full advisory is several billed segments — --dry-run prints the real count.

Numbers must be E.164 WITH a leading + (e.g. +919876543210) — Twilio's format.
WhatsApp's sender wants the same numbers WITHOUT the +; don't reuse one for the other.
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "services"))
from varshadrishti.data import supabase_client as SB  # noqa: E402
from advisory_text import compose  # noqa: E402


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
    if not sid or not token or not from_number:
        sys.exit("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER missing — see .env.example")
    return sid, token, from_number


def plain_text(body: str) -> str:
    return re.sub(r"[*_]", "", body)


def call(sid: str, token: str, **params) -> dict:
    url = API.format(sid=sid)
    body = urllib.parse.urlencode(params).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def resolve_recipients(override: str | None) -> list[str]:
    """Numbers to send to, in order: CLI override -> Supabase -> env.

    No local-file fallback — same reasoning as WhatsApp's resolve_recipients.
    """
    if override:
        return [override]
    subs = SB.fetch_subscribers(channel="sms")
    if subs:
        return [s["destination"] for s in subs]
    if os.environ.get("TWILIO_TEST_RECIPIENT"):
        return [os.environ["TWILIO_TEST_RECIPIENT"]]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="KGIS-H-180901")
    ap.add_argument("--to", help="override; otherwise Supabase or TWILIO_TEST_RECIPIENT")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = plain_text(compose(ROOT / "forecast" / "area" / f"{args.area}.json"))

    if args.dry_run:
        segments = -(-len(text) // 67)
        print(text)
        print(f"\n[{len(text)} chars, ~{segments} SMS segment{'s' if segments != 1 else ''} — Kannada is UCS-2]")
        return 0

    sid, token, from_number = load_env()
    recipients = resolve_recipients(args.to)
    if not recipients:
        sys.exit("no recipient — set TWILIO_TEST_RECIPIENT, add a Supabase subscriber, or pass --to")

    ok = 0
    for to in recipients:
        r = call(sid, token, To=to, From=from_number, Body=text)
        status = r.get("status")
        sent = status in ("queued", "sent", "accepted")
        print(f"  {to}: {status if sent else r.get('message', r)}")
        ok += 1 if sent else 0

    # Best-effort — a failed log must never undo a send that already went out.
    SB.log_broadcast(area_ids=[args.area], event="p_dry7", lead="w1", channel="sms",
                     recipient_count=ok, triggered_by="cli")
    return 0


if __name__ == "__main__":
    sys.exit(main())
