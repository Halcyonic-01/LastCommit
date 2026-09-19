"""Send today's advisory to Telegram subscribers. Reads the same JSON the app reads."""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUBS = ROOT / "services" / "telegram" / "subscribers.json"
API = "https://api.telegram.org/bot{token}/{method}"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not tok:
        sys.exit("TELEGRAM_BOT_TOKEN missing — see .env.example")
    return tok


def call(token, method, **params):
    url = API.format(token=token, method=method)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def compose(area_file: Path) -> str:
    d = json.loads(area_file.read_text(encoding="utf-8"))
    f, skill = d["forecast"], d["skill"]
    horizon = skill.get("advisory_horizon_weeks", 2)
    leads = ["w1", "w2", "w3", "w4"][:horizon]
    worst = max(f["p_dry7"][k] for k in leads)
    name = f.get("name_kn") or f["name_en"]

    head = "\U0001f7e0 *ಮಳೆ ಇಲ್ಲ — ಬಿತ್ತನೆ ಮುಂದೂಡಿ*" if worst >= 0.5 else (
        "\U0001f7e1 *ಮಳೆ ಕಡಿಮೆ — ಕಾಯಿರಿ*" if worst >= 0.25 else "\U0001f7e2 *ಮಳೆ ಬರುತ್ತದೆ*")
    lines = [
        head,
        f"{name}, {f.get('district_en','')}",
        "",
        f"ಒಣ ಅವಧಿಯ ಸಾಧ್ಯತೆ: *{round(f['p_dry7']['w1'] * 100)}%* ಈ ವಾರ, "
        f"*{round(f['p_dry7']['w2'] * 100)}%* ಮುಂದಿನ ವಾರ",
    ]
    for a in f.get("advisories", [])[:2]:
        lines += ["", f"✅ {a['action_kn']}", f"_{a['action_en']}_"]
        if a.get("reason_kn"):
            lines.append(a["reason_kn"])
        lines.append(f"ಮೂಲ: {a['source']['doc']}, table {a['source']['table']}")
    lines += ["", f"_ವಾರ 3-4 ಅಂದಾಜು ಮಾತ್ರ · bulletin {d['meta']['valid_from']}_"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="KGIS-H-180901")
    ap.add_argument("--chat-id", help="override; otherwise TELEGRAM_CHAT_ID or subscribers.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = load_env()
    text = compose(ROOT / "forecast" / "area" / f"{args.area}.json")

    if args.dry_run:
        print(text)
        return 0

    chats = [args.chat_id] if args.chat_id else []
    if not chats and os.environ.get("TELEGRAM_CHAT_ID"):
        chats = [os.environ["TELEGRAM_CHAT_ID"]]
    if not chats and SUBS.exists():
        chats = [s["chat_id"] for s in json.loads(SUBS.read_text()).get("subscribers", [])]
    if not chats:
        sys.exit("no chat id — set TELEGRAM_CHAT_ID or add services/telegram/subscribers.json")

    for cid in chats:
        r = call(token, "sendMessage", chat_id=cid, text=text, parse_mode="Markdown")
        print(f"  {cid}: {'ok' if r.get('ok') else r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
