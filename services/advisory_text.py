"""Kannada advisory text, shared by every channel: the farmer app, WhatsApp, SMS.

One composer, so no channel can drift into showing different advice from another.
The *bold*/_italic_ markers are WhatsApp's own convention and the farmer app renders
them; services/notify/providers.py strips them for SMS, which cannot show them.
"""

import json
from pathlib import Path


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
