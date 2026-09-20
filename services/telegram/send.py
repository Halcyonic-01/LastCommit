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

sys.path.insert(0, str(ROOT / "src"))
from varshadrishti.data import supabase_client as SB  # noqa: E402


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


def resolve_chats(override: str | None) -> list[str]:
    """Chat ids to send to, in order: CLI override -> Supabase -> env -> local file.

    Supabase before the single-chat env var so a real subscriber list, once populated,
    is used automatically without anyone having to remember to stop passing --chat-id.
    """
    if override:
        return [override]
    subs = SB.fetch_subscribers(channel="telegram")
    if subs:
        return [s["destination"] for s in subs]
    if os.environ.get("TELEGRAM_CHAT_ID"):
        return [os.environ["TELEGRAM_CHAT_ID"]]
    if SUBS.exists():
        return [s["chat_id"] for s in json.loads(SUBS.read_text()).get("subscribers", [])]
    return []


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

    chats = resolve_chats(args.chat_id)
    if not chats:
        sys.exit("no chat id — set TELEGRAM_CHAT_ID, add a Supabase subscriber, "
                 "or add services/telegram/subscribers.json")

    ok = 0
    for cid in chats:
        r = call(token, "sendMessage", chat_id=cid, text=text, parse_mode="Markdown")
        print(f"  {cid}: {'ok' if r.get('ok') else r}")
        ok += 1 if r.get("ok") else 0

    # Best-effort — a failed log must never undo a send that already went out.
    SB.log_broadcast(area_ids=[args.area], event="p_dry7", lead="w1", channel="telegram",
                     recipient_count=ok, triggered_by="cli")
    return 0


if __name__ == "__main__":
    sys.exit(main())
