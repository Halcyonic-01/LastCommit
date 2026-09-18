"""Verify the Telegram bot token, discover chat ids, and send a test advisory.

Run after creating the bot with @BotFather and putting the token in .env:
    .venv/bin/python scripts/telegram_setup.py            # verify + list chat ids
    .venv/bin/python scripts/telegram_setup.py --send     # also send a test card
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.telegram.org/bot{token}/{method}"


def load_env():
    """Minimal .env reader — no dependency, and it never prints the token."""
    env = ROOT / ".env"
    if not env.exists():
        sys.exit("no .env — copy .env.example to .env and add TELEGRAM_BOT_TOKEN")
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN is empty in .env")
    return token


def call(token, method, **params):
    url = API.format(token=token, method=method)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="send a test advisory card")
    args = ap.parse_args()

    token = load_env()

    me = call(token, "getMe")
    if not me.get("ok"):
        sys.exit(f"token rejected: {me}")
    bot = me["result"]
    print(f"bot ok: @{bot['username']}  ({bot['first_name']})")

    updates = call(token, "getUpdates")
    chats = {}
    for u in updates.get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("first_name") or chat.get("title") or chat.get("username")

    if not chats:
        print("\nno chats yet — open Telegram, find your bot, and send it /start")
        print("then rerun this script")
        return 1

    print(f"\n{len(chats)} chat(s) found:")
    for cid, name in chats.items():
        print(f"  {cid}  {name}")
    print("\nadd to .env:")
    print(f"  TELEGRAM_CHAT_ID={list(chats)[0]}")

    if args.send:
        text = (
            "\U0001f7e0 *VarshaDrishti* — ತುಮಕೂರು\n\n"
            "ಮುಂದಿನ 7 ದಿನ ಮಳೆ "
            "ಇಲ್ಲ — ಬಿತ್ತನೆ "
            "ಮುಂದೂಡಿ\n"
            "_No rain next 7 days — delay sowing_\n\n"
            "Dry spell risk: *32%* this week, *41%* next\n"
            "Source: ICAR-CRIDA Tumakuru plan, table 2.1.1"
        )
        for cid in chats:
            r = call(token, "sendMessage", chat_id=cid, text=text, parse_mode="Markdown")
            print(f"\nsent to {cid}: {'ok' if r.get('ok') else r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
