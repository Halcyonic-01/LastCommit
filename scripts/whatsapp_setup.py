"""Verify the WhatsApp Cloud API credentials and register test recipients.

Run after creating a Meta developer app + WhatsApp product and putting the phone
number id + access token in .env:
    .venv/bin/python scripts/whatsapp_setup.py                       # verify only
    .venv/bin/python scripts/whatsapp_setup.py --register 91XXXXXXXXXX  # + add subscriber
    .venv/bin/python scripts/whatsapp_setup.py --register 91XXXXXXXXXX --send  # + test message

Unlike Telegram's getUpdates, the Cloud API has no way to *discover* who has
messaged your number — inbound messages only ever arrive at a webhook, which this
project doesn't run. So recipients can't be auto-registered: add each number as a
"verified recipient" in the Meta App Dashboard first (Cloud API test numbers only
message numbers they've explicitly verified), then pass it to --register here so
services/whatsapp/send.py picks it up from Supabase automatically.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH = "https://graph.facebook.com/v26.0/{path}"

sys.path.insert(0, str(ROOT / "src"))
from varshadrishti.data import supabase_client as SB  # noqa: E402


def load_env():
    """Minimal .env reader — no dependency, and it never prints the token."""
    env = ROOT / ".env"
    if not env.exists():
        sys.exit("no .env — copy .env.example to .env and add WHATSAPP_PHONE_NUMBER_ID / WHATSAPP_ACCESS_TOKEN")
    env_vars = {}
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    phone_id = env_vars.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    token = env_vars.get("WHATSAPP_ACCESS_TOKEN", "").strip()
    if not phone_id or not token:
        sys.exit("WHATSAPP_PHONE_NUMBER_ID / WHATSAPP_ACCESS_TOKEN empty in .env")
    return phone_id, token


def get(token: str, path: str, **params) -> dict:
    url = GRAPH.format(path=path)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def post(token: str, path: str, payload: dict) -> dict:
    url = GRAPH.format(path=path)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", help="verified recipient phone number (E.164, no +) to add as a subscriber")
    ap.add_argument("--area", default="KGIS-H-180901", help="area the new subscriber is registered for")
    ap.add_argument("--lang", default="kn", help="language the new subscriber is registered with")
    ap.add_argument("--send", action="store_true", help="also send the hello_world test template")
    args = ap.parse_args()

    phone_id, token = load_env()

    me = get(token, phone_id, fields="verified_name,display_phone_number,quality_rating")
    if "error" in me:
        sys.exit(f"credentials rejected: {me['error']}")
    print(f"sending number ok: {me.get('display_phone_number')}  "
          f"({me.get('verified_name')}, quality={me.get('quality_rating', '?')})")

    if not args.register:
        print("\npass --register <verified phone number> to add a subscriber "
              "(add the number as a verified recipient in the Meta App Dashboard first)")
        return 0

    if SB.client() is not None:
        ok = SB.add_subscriber(area_id=args.area, channel="whatsapp",
                               destination=args.register, lang=args.lang)
        print(f"\nregistered {args.register} as subscriber (area={args.area}, lang={args.lang}): "
              f"{'ok' if ok else 'FAILED'}")
    else:
        print("\nSupabase not configured — add to .env instead:")
        print(f"  WHATSAPP_TEST_RECIPIENT={args.register}")

    if args.send:
        r = post(token, f"{phone_id}/messages", {
            "messaging_product": "whatsapp", "to": args.register,
            "type": "template", "template": {"name": "hello_world", "language": {"code": "en_US"}},
        })
        print(f"\nsent to {args.register}: {'ok' if r.get('messages') else r.get('error', r)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
