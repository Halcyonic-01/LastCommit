"""Structured narration generator for VarshaDrishti farmer screens.

Strictly grounded in forecast JSON (probabilities, skill, CRIDA rules, metadata).
Never extracts DOM or uses page innerText.
"""
from __future__ import annotations

import re
from typing import Any

VERDICT_SPEAK = {
    "high": {
        "kn": "ಈ ವಾರ ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಕಡಿಮೆ. ಈಗ ಬಿತ್ತನೆ ಮಾಡಬೇಡಿ.",
        "hi": "इस हफ़्ते बारिश की उम्मीद कम है। अभी बुवाई न करें।",
        "te": "ఈ వారం వర్షం వచ్చే అవకాశం తక్కువ. ఇప్పుడు విత్తనం వేయవద్దు.",
        "en": "Little chance of rain this week. Do not sow yet.",
    },
    "caution": {
        "kn": "ಮಳೆ ಬರುವುದು ಖಚಿತವಿಲ್ಲ. ಬಿತ್ತನೆಗೆ ಸ್ವಲ್ಪ ಕಾಯಿರಿ.",
        "hi": "बारिश पक्की नहीं है। बुवाई के लिए थोड़ा रुकें।",
        "te": "వర్షం ఖచ్చితం కాదు. విత్తడానికి కొంచెం ఆగండి.",
        "en": "Rain is not certain. Wait a little before sowing.",
    },
    "ok": {
        "kn": "ಮುಂದಿನ ದಿನಗಳಲ್ಲಿ ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಇದೆ. ಬಿತ್ತನೆ ಮಾಡಬಹುದು.",
        "hi": "आने वाले दिनों में बारिश की उम्मीद है। बुवाई कर सकते हैं।",
        "te": "రాబోయే రోజుల్లో వర్షం వచ్చే అవకాశం ఉంది. విత్తనం వేయవచ్చు.",
        "en": "Rain is likely in the coming days. You can sow.",
    },
}


def out_of_ten(prob: float) -> int:
    """Frequency framing (e.g. 0.46 -> 5)."""
    return max(0, min(10, round(float(prob or 0.0) * 10)))


def advisory_horizon(skill: dict[str, Any] | None) -> int:
    """Number of lead weeks with verified forecast skill."""
    return int((skill or {}).get("advisory_horizon_weeks", 1) or 0)


def get_verdict_level(forecast: dict[str, Any], skill: dict[str, Any] | None = None) -> str:
    """Calculate verdict level: 'high', 'caution', or 'ok'."""
    p_dry = forecast.get("p_dry7", {})
    horizon = advisory_horizon(skill)
    leads = ["w1", "w2", "w3", "w4"][:horizon] if horizon > 0 else ["w1"]
    vals = [float(p_dry.get(k, 0.0) or 0.0) for k in leads]
    p_max = max(vals) if vals else 0.0
    if p_max >= 0.50:
        return "high"
    if p_max >= 0.25:
        return "caution"
    return "ok"


def ten_years_sentence(n: int, lang: str = "kn") -> str:
    """Sentence communicating 10-year historical frequency."""
    if lang == "hi":
        return f"पिछले 10 सालों में से {n} साल इसी समय एक हफ़्ते बारिश रुक गई थी।"
    if lang == "te":
        return f"గత 10 సంవత్సరాలలో {n} సంవత్సరాలు ఇదే సమయంలో ఒక వారం వర్షం ఆగిపోయింది."
    if lang == "en":
        return f"In {n} of the last 10 years like this one, the rain stopped for a week."
    return f"ಕಳೆದ 10 ವರ್ಷಗಳಲ್ಲಿ {n} ವರ್ಷ ಇದೇ ಸಮಯಕ್ಕೆ ಒಂದು ವಾರ ಮಳೆ ನಿಂತಿತ್ತು."


def why_spoken_sentence(years: Any, n: int, lang: str = "kn") -> str:
    """Sentence comparing historical records with current conditions."""
    y = str(years or "5")
    if lang == "hi":
        return f"हमने {y} सालों का बारिश का रिकॉर्ड आज की स्थिति से मिलाया। दस में से {n} साल एक हफ़्ते बारिश रुकी थी।"
    if lang == "te":
        return f"మేము {y} సంవత్సరాల వర్ష రికార్డును నేటి పరిస్థితితో పోల్చాము. పదిలో {n} సంవత్సరాలు ఒక వారం వర్షం ఆగింది."
    if lang == "en":
        return f"We compared {y} years of rainfall records with today's conditions. In {n} of 10 similar years the rain stopped for a week."
    return f"ಕಳೆದ {y} ವರ್ಷಗಳ ಮಳೆ ದಾಖಲೆಯನ್ನು ಇಂದಿನ ಸ್ಥಿತಿಯ ಜೊತೆ ಹೋಲಿಸಿದ್ದೇವೆ. ಹತ್ತರಲ್ಲಿ {n} ವರ್ಷ ಒಂದು ವಾರ ಮಳೆ ನಿಂತಿತ್ತು."


def outlook_note_sentence(horizon: int, lang: str = "kn") -> str:
    """Sentence clarifying the boundary where the forecast transitions to outlook."""
    h = horizon
    if lang == "hi":
        return f"इसीलिए यह ऐप सिर्फ़ हफ़्ते {h} तक की सलाह देता है। उसके बाद सिर्फ़ अनुमान है।" if h > 0 else "अभी किसी भी हफ़्ते के लिए सलाह नहीं दी जा सकती। सब कुछ सिर्फ़ अनुमान है।"
    if lang == "te":
        return f"అందుకే ఈ యాప్ {h}వ వారం వరకు మాత్రమే సలహా ఇస్తుంది. తర్వాత అంచనా మాత్రమే." if h > 0 else "ఇప్పుడు ఏ వారానికీ సలహా ఇవ్వలేము. అంతా అంచనా మాత్రమే."
    if lang == "en":
        return f"That is why this app only gives action through week {h}. Anything after that is outlook only." if h > 0 else "This app cannot give action for any week right now. Everything shown is outlook only."
    return f"ಈ ಆ್ಯಪ್ {h}ನೇ ವಾರದವರೆಗೆ ಮಾತ್ರ ಏನು ಮಾಡಬೇಕೆಂದು ಹೇಳುತ್ತದೆ. ಅದರ ನಂತರ ಅಂದಾಜು ಮಾತ್ರ." if h > 0 else "ಈಗ ಯಾವ ವಾರಕ್ಕೂ ಏನು ಮಾಡಬೇಕೆಂದು ಹೇಳಲಾಗುವುದಿಲ್ಲ. ಎಲ್ಲವೂ ಅಂದಾಜು ಮಾತ್ರ."


def why_sources_sentence(members: Any = 51, lang: str = "kn") -> str:
    """Provenance sources summary sentence."""
    m = str(members) if members else ""
    if lang == "hi":
        mem_clause = f", अगले चार हफ़्तों के लिए {m} ECMWF मॉडल रन" if m else ""
        return f"इस होबली का 34 साल का IMD बारिश रिकॉर्ड{mem_clause}, और फ़सल सलाह के लिए ICAR-CRIDA ज़िला योजना।"
    if lang == "te":
        mem_clause = f", రాబోయే నాలుగు వారాలకు {m} ECMWF మోడల్ రన్‌లు" if m else ""
        return f"ఈ హోబళి యొక్క 34 సంవత్సరాల IMD వర్ష రికార్డు{mem_clause}, మరియు పంట సలహా కోసం ICAR-CRIDA జిల్లా ప్రణాళిక."
    if lang == "en":
        mem_clause = f", {m} ECMWF model runs for the coming four weeks" if m else ""
        return f"34 years of IMD rainfall for this hobli{mem_clause}, and the ICAR-CRIDA district plan for the crop advice."
    mem_clause = f", ಮುಂದಿನ ನಾಲ್ಕು ವಾರಗಳಿಗೆ {m} ಇಸಿಎಂಡಬ್ಲ್ಯೂಎಫ್ ಮಾದರಿ ಓಟಗಳು" if m else ""
    return f"ಈ ಹೋಬಳಿಯ 34 ವರ್ಷಗಳ ಐಎಂಡಿ ಮಳೆ ದಾಖಲೆ{mem_clause}, ಮತ್ತು ಬೆಳೆ ಸಲಹೆಗೆ ಐಸಿಎಆರ್-ಕ್ರಿಡಾ ಜಿಲ್ಲಾ ಯೋಜನೆ."


def build_today_narration(data: dict[str, Any], lang: str = "kn") -> str:
    """Whose field, what the forecast says, 10-year probability frequency, and crop action."""
    forecast = data.get("forecast") or data
    skill = data.get("skill") or {}
    advisories = forecast.get("advisories") or []
    adv = advisories[0] if advisories else None

    # Location name
    name_kn = forecast.get("name_kn") or forecast.get("name_en", "")
    name_en = forecast.get("name_en", "")
    district_en = forecast.get("district_en", "")
    place_str = f"{name_en if lang == 'en' else (name_kn or name_en)}, {district_en}."

    # Verdict speech
    v_level = get_verdict_level(forecast, skill)
    verdict_text = VERDICT_SPEAK.get(v_level, {}).get(lang, VERDICT_SPEAK[v_level]["kn"])

    # 10 years frequency
    p_w1 = (forecast.get("p_dry7") or {}).get("w1", 0.0)
    ten_years_text = ten_years_sentence(out_of_ten(p_w1), lang=lang)

    # Advisory action
    adv_text = ""
    if adv:
        if lang == "kn":
            adv_text = adv.get("action_kn", "")
        elif lang == "en":
            adv_text = adv.get("action_en", "")
        elif lang == "hi":
            adv_text = "मिट्टी की नमी बचाएं और बारिश पर निर्भर काम टालें।"
        elif lang == "te":
            adv_text = "నేల తేమను కాపాడండి, వర్షంపై ఆధారపడిన పనులను వాయిదా వేయండి."

    parts = [place_str, verdict_text, ten_years_text, adv_text]
    return " ".join([p.strip() for p in parts if p and p.strip()])


def build_why_narration(data: dict[str, Any], lang: str = "kn") -> str:
    """The evidence, how far ahead it is trusted, and where it came from."""
    forecast = data.get("forecast") or data
    skill = data.get("skill") or {}
    p_w1 = (forecast.get("p_dry7") or {}).get("w1", 0.0)
    ten = out_of_ten(p_w1)

    seasons = skill.get("seasons_scored", 5)
    horizon = advisory_horizon(skill)

    members = 51
    prov_sum = data.get("provenance_summary") or ""
    match = re.search(r"(\d+)\s+ensemble members", prov_sum)
    if match:
        members = int(match.group(1))

    part1 = why_spoken_sentence(seasons, ten, lang=lang)
    part2 = outlook_note_sentence(horizon, lang=lang)
    part3 = why_sources_sentence(members, lang=lang)

    return f"{part1} {part2} {part3}".strip()
