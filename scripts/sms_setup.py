"""Verify Twilio credentials and register SMS test recipients.

Run after creating a Twilio account and putting Account SID / Auth Token / From
number in .env:
    .venv/bin/python scripts/sms_setup.py                            # verify only
    .venv/bin/python scripts/sms_setup.py --register +91XXXXXXXXXX   # + add subscriber
    .venv/bin/python scripts/sms_setup.py --register +91XXXXXXXXXX --send  # + test message

A trial Twilio account can only send to numbers verified in the Twilio console
(Phone Numbers -> Manage -> Verified Caller IDs) — the SMS equivalent of WhatsApp's
verified test recipients. Every trial message also gets "Sent from your Twilio
trial account -" prepended by Twilio itself; that's Twilio's own trial behaviour,
not something this script adds or can remove — it goes away once the account is
upgraded to paid.

Numbers must be E.164 WITH a leading + (Twilio's format) — the WhatsApp scripts want
the same numbers WITHOUT the +, so don't copy one field into the other verbatim.
"""

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://api.twilio.com/2010-04-01/Accounts/{sid}"

sys.path.insert(0, str(ROOT / "src"))
from varshadrishti.data import supabase_client as SB  # noqa: E402


def load_env():
    """Minimal .env reader — no dependency, and it never prints the token."""
    env = ROOT / ".env"
    if not env.exists():
        sys.exit("no .env — copy .env.example to .env and add TWILIO_ACCOUNT_SID / "
                 "TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER")
    env_vars = {}
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    sid = env_vars.get("TWILIO_ACCOUNT_SID", "").strip()
    token = env_vars.get("TWILIO_AUTH_TOKEN", "").strip()
    from_number = env_vars.get("TWILIO_FROM_NUMBER", "").strip()
    if not sid or not token or not from_number:
        sys.exit("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER empty in .env")
    return sid, token, from_number


def get(sid: str, token: str) -> dict:
    url = f"{BASE.format(sid=sid)}.json"
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def post(sid: str, token: str, path: str, **params) -> dict:
    url = f"{BASE.format(sid=sid)}/{path}"
    body = urllib.parse.urlencode(params).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", help="verified recipient phone number (E.164, with +) to add as a subscriber")
    ap.add_argument("--area", default="KGIS-H-180901", help="area the new subscriber is registered for")
    ap.add_argument("--lang", default="kn", help="language the new subscriber is registered with")
    ap.add_argument("--send", action="store_true", help="also send a short test SMS")
    args = ap.parse_args()

    sid, token, from_number = load_env()

    acct = get(sid, token)
    if "sid" not in acct:
        sys.exit(f"credentials rejected: {acct}")
    print(f"account ok: {acct.get('friendly_name')}  (type={acct.get('type', '?')}, status={acct.get('status')})")

    if not args.register:
        print("\npass --register <verified phone number, E.164 with +> to add a subscriber "
              "(verify it in the Twilio console first on a trial account)")
        return 0

    if SB.client() is not None:
        ok = SB.add_subscriber(area_id=args.area, channel="sms",
                               destination=args.register, lang=args.lang)
        print(f"\nregistered {args.register} as subscriber (area={args.area}, lang={args.lang}): "
              f"{'ok' if ok else 'FAILED'}")
    else:
        print("\nSupabase not configured — add to .env instead:")
        print(f"  TWILIO_TEST_RECIPIENT={args.register}")

    if args.send:
        r = post(sid, token, "Messages.json", To=args.register, From=from_number,
                 Body="VarshaDrishti test message - SMS channel connected.")
        print(f"\nsent to {args.register}: {r.get('status', r.get('message', r))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
