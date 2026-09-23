"""Grounded VarshaDrishti Farmer Assistant Logic.

Answers farmer questions using real forecast data, dry-spell risk, and ICAR-CRIDA
contingency advisories. No LLM hallucination of probabilities or crop advice.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
FORECAST_DIR = ROOT / "forecast" / "area"
LATEST_FORECAST_FILE = ROOT / "forecast" / "latest.json"
DEFAULT_AREA_ID = "KGIS-H-180901"  # Kasaba, Tumakuru


def load_forecast_for_area(area_id: str | None = None) -> dict[str, Any] | None:
    """Load area forecast JSON file. Falls back to default area if not found."""
    clean_id = (area_id or "").strip()
    if clean_id:
        target = FORECAST_DIR / f"{clean_id}.json"
        if target.exists():
            try:
                return json.loads(target.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("[VOICE] Error reading area forecast %s: %s", target, exc)

    default_file = FORECAST_DIR / f"{DEFAULT_AREA_ID}.json"
    if default_file.exists():
        try:
            return json.loads(default_file.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("[VOICE] Error reading default area forecast: %s", exc)

    if LATEST_FORECAST_FILE.exists():
        try:
            data = json.loads(LATEST_FORECAST_FILE.read_text(encoding="utf-8"))
            areas = data.get("areas", {})
            if clean_id and clean_id in areas:
                return {"forecast": areas[clean_id], "skill": data.get("skill", {}), "meta": data.get("meta", {})}
            if DEFAULT_AREA_ID in areas:
                return {"forecast": areas[DEFAULT_AREA_ID], "skill": data.get("skill", {}), "meta": data.get("meta", {})}
            if areas:
                first_key = next(iter(areas))
                return {"forecast": areas[first_key], "skill": data.get("skill", {}), "meta": data.get("meta", {})}
        except Exception as exc:
            log.warning("[VOICE] Error reading latest.json: %s", exc)

    return None


def get_verdict_level(forecast: dict[str, Any], skill: dict[str, Any] | None = None) -> str:
    """Calculate verdict level: 'high' (severe dry spell), 'caution', or 'ok'."""
    p_dry = forecast.get("p_dry7", {})
    horizon = (skill or {}).get("advisory_horizon_weeks", 1)
    leads = ["w1", "w2", "w3", "w4"][:horizon]
    if not leads:
        leads = ["w1"]
    vals = [p_dry.get(k, 0.0) for k in leads]
    p_max = max(vals) if vals else 0.0
    if p_max >= 0.50:
        return "high"
    if p_max >= 0.25:
        return "caution"
    return "ok"


INTENT_PATTERNS = {
    # 1. Will it rain tomorrow? / Short-lead rain
    "rain_tomorrow": {
        "kn": [
            "ನಾಳೆ ಮಳೆ", "ನಾಳೆ ಬರುತ್ತಾ", "ನಾಳೆ ಬರ್ತಾ", "ನಾಳಿನ ಮಳೆ", "ನಾಳೆ",
            "ಇಂದು ಮಳೆ", "ಇವತ್ತು ಮಳೆ", "ಮಳೆ ಬರುತ್ತಾ", "ಮಳೆ ಬರ್ತದಾ",
        ],
        "hi": ["कल बारिश", "कल की बारिश", "कल पानी", "आज बारिश", "बारिश आएगी", "बारिश होगी"],
        "te": ["రేపు వర్షం", "రేపు", "ఈరోజు వర్షం", "వర్షం వస్తుందా"],
        "en": ["tomorrow", "rain tomorrow", "will it rain tomorrow", "rain today", "will it rain"],
    },
    # 2. How will rain be this week? / Weekly outlook
    "rain_week": {
        "kn": [
            "ಈ ವಾರ ಮಳೆ", "ವಾರದ ಮಳೆ", "ವಾರ ಮಳೆ", "ವಾರ ಹೇಗಿರುತ್ತದೆ", "ವಾರ ಹೇಗಿರುತ್ತೆ",
            "ಮುಂದಿನ ದಿನಗಳಲ್ಲಿ ಮಳೆ", "ಮುಂದಿನ ವಾರ",
        ],
        "hi": ["इस हफ़्ते बारिश", "हफ़्ते की बारिश", "इस सप्ताह", "सप्ताह में बारिश", "हफ़्ते में कैसी"],
        "te": ["ఈ వారం వర్షం", "ఈ వారం ఎలా", "ఈ వారం"],
        "en": ["this week", "rain this week", "weekly forecast", "how is rain this week", "weather this week"],
    },
    # 3. What should I do if rain is heavy? (CRIDA drainage advice)
    "heavy_rain_action": {
        "kn": [
            "ಮಳೆ ಜಾಸ್ತಿ", "ಜೋರು ಮಳೆ ಆದರೆ", "ಭಾರೀ ಮಳೆ", "ಹೆಚ್ಚು ಮಳೆ", "ಮಳೆ ಹೆಚ್ಚಾದರೆ",
            "ನೀರು ನಿಂತರೆ", "ತುಂಬಾ ಮಳೆ", "ಜಾಸ್ತಿ ಮಳೆ ಬಂದರೆ", "ಮಳೆ ಜಾಸ್ತಿ ಆದರೆ",
        ],
        "hi": [
            "ज़्यादा बारिश", "भारी बारिश", "तेज़ बारिश हुई तो", "ज़्यादा पानी",
            "बारिश अधिक हुई तो", "जलभराव",
        ],
        "te": ["భారీ వర్షం", "ఎక్కువ వర్షం", "భారీ వర్షం వస్తే", "ఎక్కువ వర్షం పడితే"],
        "en": ["heavy rain", "excess rain", "too much rain", "if it rains heavily", "flooding", "waterlogging"],
    },
    # 4. Should I water my crop? (Irrigation advice)
    "crop_watering": {
        "kn": [
            "ನೀರು ಹಾಕಬೇಕಾ", "ನೀರು ಕೊಡಬೇಕಾ", "ನೀರು ಹಾಯಿಸಬೇಕಾ", "ನೀರಾವರಿ", "ಬೆಳೆಗೆ ನೀರು",
            "ತೋಟಕ್ಕೆ ನೀರು", "ಹೊಲಕ್ಕೆ ನೀರು", "ನೀರುಣಿಸಬೇಕಾ",
        ],
        "hi": ["पानी देना चाहिए", "सिंचाई करनी चाहिए", "फ़सल को पानी", "पानी दें या नहीं", "सिंचाई"],
        "te": ["నీరు పెట్టాలా", "నీరు పోయాలా", "సాగునీరు", "పంటకు నీరు"],
        "en": ["water my crop", "should i water", "irrigate", "irrigation", "water the field"],
    },
    # 5. Farmer rain observation: rained
    "rain_yes": {
        "kn": ["ಮಳೆ ಬಂತು", "ಮಳೆ ಬಿತ್ತು", "ಮಳೆ ಆಯಿತು", "ಸ್ವಲ್ಪ ಮಳೆ ಬಿತ್ತು", "ನಿನ್ನೆ ಮಳೆ ಬಂತು"],
        "hi": ["बारिश हुई", "बारिश आई", "बारिश हो गई", "वर्षा हुई", "थोड़ी बारिश हुई"],
        "te": ["వర్షం పడింది", "వర్షం వచ్చింది", "వర్షం కురిసింది", "కొంచెం వర్షం"],
        "en": ["it rained", "rain yesterday", "rained yesterday", "rained"],
    },
    # 6. Farmer rain observation: no rain
    "rain_no": {
        "kn": ["ಮಳೆ ಇಲ್ಲ", "ಮಳೆ ಬರಲಿಲ್ಲ", "ಮಳೆ ಆಗಲಿಲ್ಲ", "ಮಳೆ ನಿಂತಿದೆ", "ಒಣ ಹವೆ"],
        "hi": ["बारिश नहीं", "बारिश नहीं हुई", "वर्षा नहीं", "सूखा है"],
        "te": ["వర్షం లేదు", "వర్షం పడలేదు", "వర్షం రాలేదు"],
        "en": ["no rain", "did not rain", "dry day", "no rainfall"],
    },
    # 7. Sowing / CRIDA Advisory
    "advisory": {
        "kn": ["ಬಿತ್ತನೆ", "ಸಲಹೆ", "ಏನು ಮಾಡಲಿ", "ಏನು ಮಾಡಬೇಕು", "ಮಾಹಿತಿ", "ಕೃಷಿ ಸಲಹೆ"],
        "hi": ["बुवाई", "सलाह", "क्या करूं", "क्या करना", "जानकारी", "कृषि सलाह"],
        "te": ["విత్తనాలు", "సలహా", "ఏమి చేయాలి", "సమాచారం", "వ్యవసాయ సలహా"],
        "en": ["sow", "sowing", "advice", "what to do", "advisory", "suggest"],
    },
    # 8. Repeat
    "repeat": {
        "kn": ["ಮತ್ತೆ", "ಮತ್ತೊಮ್ಮೆ", "ಮರುಕಳಿಸಿ", "ಮತ್ತೆ ಹೇಳಿ", "ಇನ್ನೊಮ್ಮೆ ಹೇಳಿ"],
        "hi": ["फिर से", "दोबारा", "फिर बोलो", "दुबारा சொல்ல"],
        "te": ["మళ్ళీ", "మళ్ళీ చెప్పండి", "మరోసారి"],
        "en": ["repeat", "again", "say again", "once more"],
    },
}


def classify_intent(text: str, lang: str = "kn") -> str:
    """Classify user query into an agricultural or conversational intent."""
    text_lower = text.lower().strip()
    norm_lang = lang.lower().split("-")[0]

    # Priority check: check specific domain intents before general ones
    priority_order = [
        "heavy_rain_action",
        "crop_watering",
        "rain_no",
        "rain_yes",
        "rain_week",
        "rain_tomorrow",
        "advisory",
        "repeat",
    ]

    for intent in priority_order:
        lang_phrases = INTENT_PATTERNS[intent].get(norm_lang, [])
        for phrase in lang_phrases:
            if phrase.lower() in text_lower:
                return intent

    # Check other languages as fallback in case input is bilingual / code-mixed
    for intent in priority_order:
        for other_lang, phrases in INTENT_PATTERNS[intent].items():
            if other_lang != norm_lang:
                for phrase in phrases:
                    if phrase.lower() in text_lower:
                        return intent

    return "unknown"


def generate_grounded_answer(
    transcript: str,
    lang: str = "kn",
    area_id: str | None = None,
) -> dict[str, Any]:
    """Generate a fully grounded answer using the VarshaDrishti forecast and CRIDA rules.
    
    Returns a dict with 'action', 'reply_text', and 'grounding_data'.
    """
    clean_lang = lang.lower().split("-")[0]
    if clean_lang not in ("kn", "hi", "te", "en"):
        clean_lang = "kn"

    data = load_forecast_for_area(area_id)
    if not data or "forecast" not in data:
        # Fallback if forecast data unavailable
        return {
            "action": "unknown",
            "reply_text": {
                "kn": "ಕ್ಷಮಿಸಿ, ಹವಾಮಾನ ಮುನ್ಸೂಚನೆ ಮಾಹಿತಿ ಪಡೆಯಲು ಸಾಧ್ಯವಾಗುತ್ತಿಲ್ಲ.",
                "hi": "क्षमा करें, मौसम पूर्वानुमान की जानकारी नहीं मिल सकी।",
                "te": "క్షమించండి, వాతావరణ సమాచారం అందుబాటులో లేదు.",
                "en": "Sorry, could not load weather forecast information.",
            }[clean_lang],
            "grounding_data": {},
        }

    forecast = data["forecast"]
    skill = data.get("skill", {})
    verdict = get_verdict_level(forecast, skill)

    place_kn = forecast.get("name_kn") or forecast.get("name_en", "ನಿಮ್ಮ ಪ್ರದೇಶ")
    place_en = forecast.get("name_en", "Your area")
    p_dry_w1 = float(forecast.get("p_dry7", {}).get("w1", 0.35))
    ten = max(0, min(10, round(p_dry_w1 * 10)))
    advisories = forecast.get("advisories", [])
    primary_adv = advisories[0] if advisories else None

    intent = classify_intent(transcript, clean_lang)

    # 1. Rain Tomorrow / Short-term
    if intent == "rain_tomorrow":
        if verdict == "high":
            replies = {
                "kn": f"{place_kn}: ಮುಂದಿನ ದಿನಗಳಲ್ಲಿ ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಕಡಿಮೆ. ಈ ವಾರ ಒಣ ಹವೆ ಮುಂದುವರಿಯುವ ಸಾಧ್ಯತೆ ಇದೆ.",
                "hi": f"{place_en}: आने वाले दिनों में बारिश की संभावना कम है। इस हफ़्ते सूखा मौसम रहने की संभावना है।",
                "te": f"{place_en}: రాబోయే రోజుల్లో వర్షం వచ్చే అవకాశం తక్కువ. ఈ వారం పొడి వాతావరణం కొనసాగవచ్చు.",
                "en": f"{place_en}: Little chance of rain in the coming days. Dry weather is likely this week.",
            }
        elif verdict == "caution":
            replies = {
                "kn": f"{place_kn}: ನಾಳೆ ಮತ್ತು ಮುಂದಿನ ದಿನಗಳಲ್ಲಿ ಮಳೆ ಬರುವುದು ಖಚಿತವಿಲ್ಲ. ಬಿತ್ತನೆಗೆ ಸ್ವಲ್ಪ ಕಾಯಿರಿ.",
                "hi": f"{place_en}: कल और आने वाले दिनों में बारिश पक्की नहीं है। बुवाई के लिए थोड़ा इंतज़ार करें।",
                "te": f"{place_en}: రేపు మరియు రాబోయే రోజుల్లో వర్షం ఖచ్చితం కాదు. విత్తడానికి కొంచెం వేచి ఉండండి.",
                "en": f"{place_en}: Rain is not certain tomorrow or the coming days. Wait a little before sowing.",
            }
        else:
            replies = {
                "kn": f"{place_kn}: ಮುಂದಿನ ದಿನಗಳಲ್ಲಿ ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಇದೆ.",
                "hi": f"{place_en}: आने वाले दिनों में बारिश आने की संभावना है।",
                "te": f"{place_en}: రాబోయే రోజుల్లో వర్షం వచ్చే అవకాశం ఉంది.",
                "en": f"{place_en}: Rain is likely in the coming days.",
            }
        return {
            "action": intent,
            "reply_text": replies[clean_lang],
            "grounding_data": {"verdict": verdict, "p_dry7_w1": p_dry_w1, "place": place_en},
        }

    # 2. Rain This Week
    if intent == "rain_week":
        adv_kn = f" {primary_adv['action_kn']}." if primary_adv and clean_lang == "kn" else ""
        adv_en = f" {primary_adv['action_en']}." if primary_adv and clean_lang == "en" else ""
        if verdict == "high":
            replies = {
                "kn": f"{place_kn}: ಈ ವಾರ ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಕಡಿಮೆ. ಕಳೆದ 10 ವರ್ಷಗಳಲ್ಲಿ {ten} ವರ್ಷ ಇದೇ ಸಮಯಕ್ಕೆ ಒಂದು ವಾರ ಮಳೆ ನಿಂತಿತ್ತು.{adv_kn}",
                "hi": f"{place_en}: इस हफ़्ते बारिश की संभावना कम है। पिछले 10 सालों में से {ten} साल बारिश रुकी थी।",
                "te": f"{place_en}: ఈ వారం వర్షం వచ్చే అవకాశం తక్కువ. గత 10 సంవత్సరాలలో {ten} సంవత్సరాలు వర్షం ఆగింది.",
                "en": f"{place_en}: Little chance of rain this week. In {ten} of the last 10 similar years the rain stopped.{adv_en}",
            }
        elif verdict == "caution":
            replies = {
                "kn": f"{place_kn}: ಮಳೆ ಬರುವುದು ಖಚಿತವಿಲ್ಲ. ಕಳೆದ 10 ವರ್ಷಗಳಲ್ಲಿ {ten} ವರ್ಷ ಇದೇ ಸಮಯಕ್ಕೆ ಒಂದು ವಾರ ಮಳೆ ನಿಂತಿತ್ತು. ಬಿತ್ತನೆಗೆ ಸ್ವಲ್ಪ ಕಾಯಿರಿ.{adv_kn}",
                "hi": f"{place_en}: बारिश पक्की नहीं है। पिछले 10 सालों में से {ten} साल बारिश रुकी थी। बुवाई के लिए रुकें।",
                "te": f"{place_en}: వర్షం ఖచ్చితం కాదు. గత 10 సంవత్సరాలలో {ten} సంవత్సరాలు వర్షం ఆగింది. విత్తడానికి ఆగండి.",
                "en": f"{place_en}: Rain is not certain. In {ten} of 10 similar years the rain stopped. Wait before sowing.{adv_en}",
            }
        else:
            replies = {
                "kn": f"{place_kn}: ಈ ವಾರ ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಇದೆ. ಬಿತ್ತನೆ ಮಾಡಬಹುದು.{adv_kn}",
                "hi": f"{place_en}: आने वाले दिनों में बारिश आने की संभावना है। बुवाई कर सकते हैं।",
                "te": f"{place_en}: రాబోయే రోజుల్లో వర్షం వచ్చే అవకాశం ఉంది. విత్తనం వేయవచ్చు.",
                "en": f"{place_en}: Rain is likely in the coming days. You can sow.{adv_en}",
            }
        return {
            "action": intent,
            "reply_text": replies[clean_lang],
            "grounding_data": {"verdict": verdict, "p_dry7_w1": p_dry_w1, "ten_years": ten},
        }

    # 3. Heavy Rain Precaution (CRIDA Drainage Rule 2.2)
    if intent == "heavy_rain_action":
        replies = {
            "kn": "ಭಾರೀ ಮಳೆಯಾದರೆ ಹೊಲದಲ್ಲಿ ನೀರು ನಿಲ್ಲದಂತೆ ಕಾಲುವೆ ಮಾಡಿ ನೀರನ್ನು ಹೊರಹಾಕಿ. ಬೆಳೆ ಸಿದ್ಧವಿದ್ದರೆ ಕೊಯ್ಲು ಮಾಡಿ.",
            "hi": "भारी बारिश होने पर खेत में जलभराव रोकने के लिए नालियाँ बनाएँ। फ़सल तैयार हो तो कटाई करें।",
            "te": "భారీ వర్షం పడితే పొలంలో నీరు నిల్వ ఉండకుండా కాలువలు తీయండి. పంట సిద్ధంగా ఉంటే కోయండి.",
            "en": "Open drainage channels in the field to prevent waterlogging. Harvest promptly if the crop is ready.",
        }
        return {
            "action": intent,
            "reply_text": replies[clean_lang],
            "grounding_data": {"rule_id": "heavyrain.drainage", "source": "CRIDA Table 2.2"},
        }

    # 4. Irrigation / Crop Watering
    if intent == "crop_watering":
        if p_dry_w1 >= 0.25:
            replies = {
                "kn": "ಈ ವಾರ ಒಣ ಅವಧಿಯ ಸಾಧ್ಯತೆ ಇರುವುದರಿಂದ, ಸಾಧ್ಯವಿದ್ದರೆ ಲಘು ರಕ್ಷಣಾ ನೀರಾವರಿ ಕೊಡಿ ಮತ್ತು ಮಣ್ಣಿನ ತೇವ ಉಳಿಸಿ.",
                "hi": "इस हफ़्ते सूखे की संभावना है, इसलिए यदि संभव हो तो हल्की जीवन-रक्षक सिंचाई करें और नमी बचाएँ।",
                "te": "ఈ వారం పొడి కాలం ఉండే అవకాశం ఉన్నందున, వీలైతే రక్షక తడి ఇవ్వండి మరియు తేమను కాపాడండి.",
                "en": "A dry spell is likely this week. Give life-saving irrigation if available and conserve soil moisture.",
            }
        else:
            replies = {
                "kn": "ಮುಂದಿನ ದಿನಗಳಲ್ಲಿ ಮಳೆ ಬರುವ ಸಾಧ್ಯತೆ ಇರುವುದರಿಂದ, ಈಗಲೇ ನೀರು ಹಾಕಬೇಡಿ.",
                "hi": "आने वाले दिनों में बारिश की संभावना है, इसलिए अभी सिंचाई न करें।",
                "te": "రాబోయే రోజుల్లో వర్షం వచ్చే అవకాశం ఉన్నందున, ఇప్పుడే నీరు పెట్టవద్దు.",
                "en": "Rain is likely in the coming days, so hold off on unnecessary irrigation for now.",
            }
        return {
            "action": intent,
            "reply_text": replies[clean_lang],
            "grounding_data": {"p_dry7_w1": p_dry_w1, "rule_id": "midseason.flowering"},
        }

    # 5. Rain Report: Yes
    if intent == "rain_yes":
        replies = {
            "kn": "ಧನ್ಯವಾದ. ನಿಮ್ಮ ಮಳೆ ವರದಿ ದಾಖಲಾಗಿದೆ.",
            "hi": "धन्यवाद। आपकी बारिश की सूचना दर्ज हो गई।",
            "te": "ధన్యవాదాలు. మీ వర్షం నివేదిక నమోదైంది.",
            "en": "Thank you. Your rain report has been recorded.",
        }
        return {"action": intent, "reply_text": replies[clean_lang], "grounding_data": {}}

    # 6. Rain Report: No
    if intent == "rain_no":
        replies = {
            "kn": "ಧನ್ಯವಾದ. ಮಳೆ ಇಲ್ಲ ಎಂದು ದಾಖಲಾಗಿದೆ.",
            "hi": "धन्यवाद। बारिश नहीं हुई, यह दर्ज हो गया।",
            "te": "ధన్యవాదాలు. వర్షం లేదని నమోదైంది.",
            "en": "Thank you. No rain today has been recorded.",
        }
        return {"action": intent, "reply_text": replies[clean_lang], "grounding_data": {}}

    # 7. Sowing / General CRIDA Advisory
    if intent == "advisory":
        if primary_adv:
            adv_text = primary_adv["action_kn"] if clean_lang == "kn" else primary_adv["action_en"]
            reason_text = primary_adv.get("reason_kn") if clean_lang == "kn" else primary_adv.get("reason_en")
            full_text = f"{adv_text}. {reason_text}." if reason_text else f"{adv_text}."
        else:
            full_text = {
                "kn": "ಮಣ್ಣಿನ ತೇವ ಉಳಿಸಿ, ಈ ವಾರ ಮಳೆಯ ಅಗತ್ಯವಿರುವ ಕೆಲಸ ಮುಂದೂಡಿ.",
                "hi": "मिट्टी की नमी बनाए रखें, बारिश पर निर्भर काम टाल दें।",
                "te": "నేలలో తేమను నిలుపుకోండి, వర్షంపై ఆధారపడే పనులను వాయిదా వేయండి.",
                "en": "Conserve soil moisture. Delay farm work that depends on rain.",
            }[clean_lang]
        return {
            "action": intent,
            "reply_text": full_text,
            "grounding_data": {"rule_id": primary_adv.get("rule_id") if primary_adv else "default"},
        }

    # 8. Repeat
    if intent == "repeat":
        replies = {
            "kn": "ಸಲಹೆ ಮತ್ತೆ ಓದಲಾಗುತ್ತಿದೆ.",
            "hi": "सलाह फिर से पढ़ी जा रही है।",
            "te": "సలహా మళ్ళీ చదవబడుతోంది.",
            "en": "Repeating the advisory now.",
        }
        return {"action": intent, "reply_text": replies[clean_lang], "grounding_data": {}}

    # Default / Unknown
    replies = {
        "kn": f"{place_kn}: ಮಳೆ ಬರುವುದು ಖಚಿತವಿಲ್ಲ. ಮಳೆ, ಬಿತ್ತನೆ, ನೀರಾವರಿ ಅಥವಾ ಕೃಷಿ ಸಲಹೆ ಬಗ್ಗೆ ಕೇಳಿ.",
        "hi": f"{place_en}: समझ में नहीं आया। कृपया बारिश, बुवाई, सिंचाई या सलाह के बारे में पूछें।",
        "te": f"{place_en}: అర్థం కాలేదు. దయచేసి వర్షం, విత్తనాలు లేదా సాగునీటి గురించి అడగండి.",
        "en": f"{place_en}: I didn't quite catch that. Please ask about rain, sowing, watering, or crop advisory.",
    }
    return {"action": "unknown", "reply_text": replies[clean_lang], "grounding_data": {}}
