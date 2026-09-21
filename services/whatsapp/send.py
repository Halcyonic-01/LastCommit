"""Send today's advisory to WhatsApp subscribers via the Meta Cloud API.

Two send modes, because WhatsApp (unlike Telegram) only allows free-form text inside
a 24h window after the recipient last messaged the business number — outside that
window Meta rejects it (error 131047) and a pre-approved template is required instead:

    --dry-run                 print the text, send nothing
    (default)                 free-form Kannada advisory text — works within the 24h
                               session window, i.e. the recipient messaged the bot recently
    --template NAME --lang L  a pre-approved template — works any time, no session needed.
                               "hello_world"/"en_US" is Meta's always-approved test template;
                               a real advisory template needs approval in Meta Business
                               Manager first (not something this script can do for you).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH = "https://graph.facebook.com/v26.0/{phone_number_id}/messages"

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
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
    if not phone_id or not token:
        sys.exit("WHATSAPP_PHONE_NUMBER_ID / WHATSAPP_ACCESS_TOKEN missing — see .env.example")
    return phone_id, token


def call(phone_id: str, token: str, payload: dict) -> dict:
    url = GRAPH.format(phone_number_id=phone_id)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def resolve_recipients(override: str | None) -> list[str]:
    """Numbers to send to, in order: CLI override -> Supabase -> env.

    No local-file fallback here — unlike Telegram, WhatsApp has no discovery API
    (see whatsapp_setup.py), so Supabase is the only real subscriber list.
    """
    if override:
        return [override]
    subs = SB.fetch_subscribers(channel="whatsapp")
    if subs:
        return [s["destination"] for s in subs]
    if os.environ.get("WHATSAPP_TEST_RECIPIENT"):
        return [os.environ["WHATSAPP_TEST_RECIPIENT"]]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="KGIS-H-180901")
    ap.add_argument("--to", help="override; otherwise Supabase or WHATSAPP_TEST_RECIPIENT")
    ap.add_argument("--template", help="send a pre-approved template instead of free text")
    ap.add_argument("--lang", default="en_US", help="template language code")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = compose(ROOT / "forecast" / "area" / f"{args.area}.json")
    if args.dry_run:
        print(text if not args.template else f"[template {args.template}/{args.lang}]")
        return 0

    phone_id, token = load_env()
    recipients = resolve_recipients(args.to)
    if not recipients:
        sys.exit("no recipient — set WHATSAPP_TEST_RECIPIENT, add a Supabase subscriber, "
                 "or pass --to")

    ok = 0
    for to in recipients:
        if args.template:
            payload = {"messaging_product": "whatsapp", "to": to, "type": "template",
                      "template": {"name": args.template, "language": {"code": args.lang}}}
        else:
            payload = {"messaging_product": "whatsapp", "to": to, "type": "text",
                      "text": {"body": text, "preview_url": False}}
        r = call(phone_id, token, payload)
        print(f"  {to}: {'ok' if r.get('messages') else r.get('error', r)}")
        ok += 1 if r.get("messages") else 0

    # Best-effort — a failed log must never undo a send that already went out.
    SB.log_broadcast(area_ids=[args.area], event="p_dry7", lead="w1", channel="whatsapp",
                     recipient_count=ok, triggered_by="cli")
    return 0


if __name__ == "__main__":
    sys.exit(main())
