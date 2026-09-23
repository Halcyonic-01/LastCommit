"""Proactive Weather Alerts and 6:00 AM Morning Briefings for WhatsApp.

Monitors VarshaDrishti forecast risk thresholds, generates ICAR-CRIDA grounded
advisories in the farmer's language, and sends voice notes and text messages
with deduplication to prevent alert fatigue.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from services.voice.assistant import load_forecast_for_area, get_verdict_level
from services.voice.providers import (
    VoiceProvider,
    get_voice_provider,
    convert_wav_to_opus_ogg,
    TTSError,
)
from services.whatsapp.service import (
    WhatsAppBackend,
    WhatsAppService,
    normalize_phone,
)
from services.notify import store

log = logging.getLogger(__name__)

# --- Risk Thresholds (Grounded in ICAR-CRIDA & VarshaDrishti) -----------------
HEAVY_RAIN_THRESHOLD = 0.30       # p_heavy.w1 >= 0.30 -> CRIDA Table 2.2 drainage alert
SEVERE_DRY_SPELL_THRESHOLD = 0.50 # p_dry7.w1 >= 0.50 -> CRIDA Table 2.1.1 severe dry spell
CAUTION_DRY_SPELL_THRESHOLD = 0.30# p_dry7.w1 >= 0.30 -> CRIDA Table 2.1.1 delay sowing
ONSET_DELAY_THRESHOLD = 3.0       # onset_delay_weeks >= 3.0 weeks
RAIN_DELTA_THRESHOLD = 0.20       # jump >= 20% compared to previous bulletin


def today_date_str() -> str:
    """Return current date in UTC as YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def evaluate_area_alerts(
    area_id: str,
    prev_forecast: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate whether any weather risk thresholds are crossed for an area."""
    data = load_forecast_for_area(area_id)
    if not data or "forecast" not in data:
        return []

    fc = data["forecast"]
    alerts = []

    p_heavy_w1 = float(fc.get("p_heavy", {}).get("w1", 0.0))
    p_dry7_w1 = float(fc.get("p_dry7", {}).get("w1", 0.0))
    onset_delay = float(fc.get("onset_delay_weeks", 0.0))

    # 1. Heavy Rain Alert
    if p_heavy_w1 >= HEAVY_RAIN_THRESHOLD:
        alerts.append({
            "type": "heavy_rain",
            "severity": "warn",
            "prob": p_heavy_w1,
            "threshold": HEAVY_RAIN_THRESHOLD,
            "rule_id": "heavyrain.drainage",
            "forecast": fc,
        })

    # 2. Severe Dry Spell Alert
    if p_dry7_w1 >= SEVERE_DRY_SPELL_THRESHOLD:
        alerts.append({
            "type": "severe_dry_spell",
            "severity": "danger",
            "prob": p_dry7_w1,
            "threshold": SEVERE_DRY_SPELL_THRESHOLD,
            "rule_id": "dryspell.postsowing",
            "forecast": fc,
        })
    elif p_dry7_w1 >= CAUTION_DRY_SPELL_THRESHOLD:
        alerts.append({
            "type": "caution_dry_spell",
            "severity": "warn",
            "prob": p_dry7_w1,
            "threshold": CAUTION_DRY_SPELL_THRESHOLD,
            "rule_id": "dryspell.postsowing",
            "forecast": fc,
        })

    # 3. Monsoon Onset Delay Alert
    if onset_delay >= ONSET_DELAY_THRESHOLD:
        alerts.append({
            "type": "onset_delay",
            "severity": "warn",
            "delay_weeks": onset_delay,
            "threshold": ONSET_DELAY_THRESHOLD,
            "rule_id": "monsoon.delay",
            "forecast": fc,
        })

    # 4. Sudden Probability Jump
    if prev_forecast:
        prev_heavy = float(prev_forecast.get("p_heavy", {}).get("w1", 0.0))
        prev_dry = float(prev_forecast.get("p_dry7", {}).get("w1", 0.0))
        if abs(p_heavy_w1 - prev_heavy) >= RAIN_DELTA_THRESHOLD or abs(p_dry7_w1 - prev_dry) >= RAIN_DELTA_THRESHOLD:
            alerts.append({
                "type": "rain_delta",
                "severity": "info",
                "delta": max(abs(p_heavy_w1 - prev_heavy), abs(p_dry7_w1 - prev_dry)),
                "threshold": RAIN_DELTA_THRESHOLD,
                "rule_id": "forecast.jump",
                "forecast": fc,
            })

    return alerts


def is_alert_already_sent(
    destination: str,
    area_id: str,
    alert_type: str,
    date_str: str | None = None,
) -> bool:
    """Check notification history to deduplicate alerts and prevent spam."""
    norm_dest = normalize_phone(destination)
    check_date = date_str or today_date_str()

    records, _ = store.recent(area_id=area_id, limit=300)
    for r in records:
        if (
            normalize_phone(r.get("destination")) == norm_dest
            and r.get("risk_event") == alert_type
            and (r.get("created_at") or "").startswith(check_date)
        ):
            return True
    return False


def build_farmer_alert(
    forecast: dict[str, Any],
    subscriber: dict[str, Any],
    alert_type: str,
    voice_provider: VoiceProvider | None = None,
) -> dict[str, Any]:
    """Dynamically construct farmer alert text and voice audio note."""
    lang = (subscriber.get("lang") or "kn").lower().split("-")[0]
    if lang not in ("kn", "hi", "te", "en"):
        lang = "kn"

    place_kn = forecast.get("name_kn") or forecast.get("name_en", "ನಿಮ್ಮ ಪ್ರದೇಶ")
    place_en = forecast.get("name_en", "Your area")
    p_heavy_pct = round(float(forecast.get("p_heavy", {}).get("w1", 0.0)) * 100)
    p_dry_pct = round(float(forecast.get("p_dry7", {}).get("w1", 0.0)) * 100)

    advisories = forecast.get("advisories", [])
    primary_adv = advisories[0] if advisories else None

    if alert_type == "heavy_rain":
        texts = {
            "kn": f"⚠️ {place_kn}: ಮುಂದಿನ ದಿನಗಳಲ್ಲಿ ಭಾರೀ ಮಳೆಯ ಮುನ್ಸೂಚನೆ ಇದೆ ({p_heavy_pct}% ಸಾಧ್ಯತೆ). ಹೊಲದಲ್ಲಿ ನೀರು ನಿಲ್ಲದಂತೆ ಬಸಿದು ಹೋಗಲು ಕಾಲುವೆ ಮಾಡಿ.",
            "hi": f"⚠️ {place_en}: आने वाले दिनों में भारी बारिश का पूर्वानुमान है ({p_heavy_pct}%)। खेत में जलभराव रोकने के लिए नालियाँ बनाएँ।",
            "te": f"⚠️ {place_en}: రాబోయే రోజుల్లో భారీ వర్ష సూచన ఉంది ({p_heavy_pct}%)। పొలంలో నీరు నిల్వ ఉండకుండా కాలువలు తీయండి.",
            "en": f"⚠️ {place_en}: Heavy rainfall expected ({p_heavy_pct}% chance). Open drainage channels to prevent waterlogging.",
        }
    elif alert_type == "severe_dry_spell":
        adv_kn = f" {primary_adv['action_kn']}." if primary_adv and lang == "kn" else ""
        adv_en = f" {primary_adv['action_en']}." if primary_adv and lang == "en" else ""
        texts = {
            "kn": f"🟠 {place_kn}: ಈ ವಾರ ತೀವ್ರ ಒಣ ಅವಧಿಯ ಸಾಧ್ಯತೆ ಇದೆ ({p_dry_pct}%). ಮಣ್ಣಿನ ತೇವ ಉಳಿಸಿ, ಮಳೆಯ ಅಗತ್ಯವಿರುವ ಕೆಲಸ ಮುಂದೂಡಿ.{adv_kn}",
            "hi": f"🟠 {place_en}: इस सप्ताह गंभीर सूखे की संभावना है ({p_dry_pct}%)। मिट्टी की नमी बचाएँ, बुवाई रोकें।",
            "te": f"🟠 {place_en}: ఈ వారం తీవ్ర పొడి వాతావరణం ఉండే అవకాశం ఉంది ({p_dry_pct}%)। నేలలో తేమను కాపాడండి.",
            "en": f"🟠 {place_en}: Severe dry spell likely this week ({p_dry_pct}%). Conserve soil moisture and delay sowing.{adv_en}",
        }
    elif alert_type == "caution_dry_spell":
        texts = {
            "kn": f"🟡 {place_kn}: ಈ ವಾರ ಮಳೆ ಬರುವುದು ಖಚಿತವಿಲ್ಲ ({p_dry_pct}% ಒಣ ಅವಧಿ). ಬಿತ್ತನೆಗೆ ಸ್ವಲ್ಪ ಕಾಯಿರಿ.",
            "hi": f"🟡 {place_en}: इस सप्ताह बारिश पक्की नहीं है ({p_dry_pct}% सूखा)। बुवाई के लिए प्रतीक्षा करें।",
            "te": f"🟡 {place_en}: ఈ వారం వర్షం ఖచ్చితం కాదు. విత్తడానికి కొంచెం వేచి ఉండండి.",
            "en": f"🟡 {place_en}: Rain is uncertain this week ({p_dry_pct}% dry risk). Wait before sowing.",
        }
    elif alert_type == "onset_delay":
        delay = forecast.get("onset_delay_weeks", 0.0)
        texts = {
            "kn": f"⏳ {place_kn}: ಮುಂಗಾರು ಆರಂಭ ಸುಮಾರು {int(delay)} ವಾರ ತಡವಾಗಿದೆ. ಅಲ್ಪಾವಧಿ ಅಥವಾ ಪರ್ಯಾಯ ಬೆಳೆಗಳಿಗೆ ಸಿದ್ಧರಾಗಿ.",
            "hi": f"⏳ {place_en}: मानसून की शुरुआत में लगभग {int(delay)} सप्ताह की देरी है। कम अवधि की फसलों की तैयारी करें।",
            "te": f"⏳ {place_en}: వర్షాకాలం ప్రారంభం ఆలస్యమైంది. ప్రత్యామ్నాయ పంటలకు సిద్ధం కావాలి.",
            "en": f"⏳ {place_en}: Monsoon onset is delayed by ~{int(delay)} weeks. Prepare for short-duration or alternate crops.",
        }
    else:
        texts = {
            "kn": f"ℹ️ {place_kn}: ಹವಾಮಾನ ಮುನ್ಸೂಚನೆಯಲ್ಲಿ ಬದಲಾವಣೆ ಕಂಡುಬಂದಿದೆ. ಹೆಚ್ಚಿನ ಮಾಹಿತಿಗಾಗಿ ಸಂಪರ್ಕಿಸಿ.",
            "hi": f"ℹ️ {place_en}: मौसम पूर्वानुमान में बदलाव हुआ है।",
            "te": f"ℹ️ {place_en}: వాతావరణ సమాచారంలో మార్పు ఉంది.",
            "en": f"ℹ️ {place_en}: Weather forecast has updated with notable changes.",
        }

    alert_text = texts.get(lang, texts["kn"])

    # Synthesize voice note if provider is present
    audio_bytes = None
    if voice_provider and voice_provider.is_configured():
        try:
            tts_res = voice_provider.synthesize(alert_text, lang=lang)
            audio_bytes = convert_wav_to_opus_ogg(tts_res.audio_bytes) or tts_res.audio_bytes
        except (TTSError, Exception) as exc:
            log.warning("[ALERT_ENGINE] Failed to synthesize alert audio: %s", exc)
            audio_bytes = None

    return {
        "text": alert_text,
        "audio_bytes": audio_bytes,
        "lang": lang,
        "alert_type": alert_type,
    }


def build_morning_briefing(
    forecast: dict[str, Any],
    subscriber: dict[str, Any],
    voice_provider: VoiceProvider | None = None,
) -> dict[str, Any]:
    """Build daily 6:00 AM weather and farming briefing for a subscriber."""
    lang = (subscriber.get("lang") or "kn").lower().split("-")[0]
    if lang not in ("kn", "hi", "te", "en"):
        lang = "kn"

    place_kn = forecast.get("name_kn") or forecast.get("name_en", "ನಿಮ್ಮ ಪ್ರದೇಶ")
    place_en = forecast.get("name_en", "Your area")
    p_dry_w1 = float(forecast.get("p_dry7", {}).get("w1", 0.0))
    p_heavy_w1 = float(forecast.get("p_heavy", {}).get("w1", 0.0))
    ten = max(0, min(10, round(p_dry_w1 * 10)))

    advisories = forecast.get("advisories", [])
    primary_adv = advisories[0] if advisories else None

    if p_heavy_w1 >= HEAVY_RAIN_THRESHOLD:
        status_kn = "ಇಂದು ಮತ್ತು ಮುಂದಿನ ದಿನಗಳಲ್ಲಿ ಭಾರೀ ಮಳೆಯಾಗುವ ಸಾಧ್ಯತೆ ಇದೆ."
        status_en = "Heavy rainfall is likely today and the coming days."
    elif p_dry_w1 >= 0.50:
        status_kn = f"ಈ ವಾರ ಒಣ ಹವೆ ಮುಂದುವರಿಯುವ ಸಾಧ್ಯತೆ ಹೆಚ್ಚು (ಕಳೆದ 10 ವರ್ಷಗಳಲ್ಲಿ {ten} ವರ್ಷ ಮಳೆ ನಿಂತಿತ್ತು)."
        status_en = f"A dry week is likely (rain stopped in {ten} of 10 similar past years)."
    elif p_dry_w1 >= 0.25:
        status_kn = f"ಮಳೆ ಬರುವುದು ಖಚಿತವಿಲ್ಲ. ಕಳೆದ 10 ವರ್ಷಗಳಲ್ಲಿ {ten} ವರ್ಷ ಇದೇ ಸಮಯಕ್ಕೆ ಮಳೆ ನಿಂತಿತ್ತು."
        status_en = f"Rain is uncertain this week. Rain stopped in {ten} of 10 past years."
    else:
        status_kn = "ಈ ವಾರ ಮಳೆ ಬರುವ ಉತ್ತಮ ಸಾಧ್ಯತೆ ಇದೆ."
        status_en = "Good probability of rain this week."

    if primary_adv:
        adv_kn = primary_adv.get("action_kn", "ಮಣ್ಣಿನ ತೇವ ಉಳಿಸಿ.")
        adv_en = primary_adv.get("action_en", "Conserve soil moisture.")
    else:
        adv_kn = "ಹವಾಮಾನಕ್ಕೆ ಅನುಗುಣವಾಗಿ ಕೃಷಿ ಕೆಲಸಗಳನ್ನು ಯೋಜಿಸಿ."
        adv_en = "Plan field work according to the weather."

    briefing_texts = {
        "kn": f"🌅 *ಶುಭೋದಯ! {place_kn} ಇಂದಿನ ಮುನ್ಸೂಚನೆ:*\n{status_kn}\n\n💡 *ಕೃಷಿ ಸಲಹೆ:* {adv_kn}",
        "hi": f"🌅 *शुभ प्रभात! {place_en} का आज का मौसम:*\n{status_en}\n\n💡 *कृषि सलाह:* {adv_en}",
        "te": f"🌅 *శుభోదయం! {place_en} నేటి వాతావరణం:*\n{status_en}\n\n💡 *వ్యవసాయ సలహా:* {adv_en}",
        "en": f"🌅 *Good Morning! Weather update for {place_en}:*\n{status_en}\n\n💡 *Advisory:* {adv_en}",
    }

    text = briefing_texts.get(lang, briefing_texts["kn"])

    audio_bytes = None
    if voice_provider and voice_provider.is_configured():
        try:
            tts_res = voice_provider.synthesize(text, lang=lang)
            audio_bytes = convert_wav_to_opus_ogg(tts_res.audio_bytes) or tts_res.audio_bytes
        except Exception as exc:
            log.warning("[ALERT_ENGINE] Failed to synthesize morning briefing audio: %s", exc)
            audio_bytes = None

    return {
        "text": text,
        "audio_bytes": audio_bytes,
        "lang": lang,
        "alert_type": "morning_briefing",
    }


def dispatch_proactive_alerts(
    backend: WhatsAppBackend,
    subscribers: list[dict[str, Any]] | None = None,
    voice_provider: VoiceProvider | None = None,
) -> list[dict[str, Any]]:
    """Scan all active WhatsApp subscribers, evaluate thresholds, and dispatch alerts."""
    provider = voice_provider or get_voice_provider()
    subs = subscribers
    if subs is None:
        service = WhatsAppService(backend=backend, voice_provider=provider)
        subs = [
            s for s in service._read_local_subscribers()
            if s.get("active", True) and s.get("channel", "whatsapp") == "whatsapp"
        ]

    dispatched = []
    today = today_date_str()

    for sub in subs:
        area_id = sub.get("area_id")
        dest = sub.get("destination")
        if not area_id or not dest:
            continue

        alerts = evaluate_area_alerts(area_id)
        for alert in alerts:
            alert_type = alert["type"]
            # Deduplication: do not send the same alert to the same farmer on the same day
            if is_alert_already_sent(dest, area_id, alert_type, today):
                log.info("[ALERT] Duplicate suppressed: %s for %s (%s)", alert_type, dest, area_id)
                continue

            content = build_farmer_alert(alert["forecast"], sub, alert_type, voice_provider=provider)
            # Dispatch via WhatsApp backend
            if content["audio_bytes"]:
                backend.send_voice(dest, content["audio_bytes"], caption=content["text"], is_ptt=True)
            backend.send_text(dest, content["text"])

            # Record in notification history for deduplication
            record_row = {
                "area_id": area_id,
                "area_name": alert["forecast"].get("name_en", area_id),
                "district": alert["forecast"].get("district_en", ""),
                "severity": alert["severity"],
                "risk_event": alert_type,
                "destination": normalize_phone(dest),
                "lang": sub.get("lang", "kn"),
                "channel": "whatsapp",
                "provider": "whatsapp",
                "status": "sent",
                "message": content["text"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            store.record(record_row)
            dispatched.append(record_row)

    return dispatched


def dispatch_morning_briefings(
    backend: WhatsAppBackend,
    subscribers: list[dict[str, Any]] | None = None,
    voice_provider: VoiceProvider | None = None,
) -> list[dict[str, Any]]:
    """Send 6:00 AM morning briefings to all active WhatsApp subscribers."""
    provider = voice_provider or get_voice_provider()
    subs = subscribers
    if subs is None:
        service = WhatsAppService(backend=backend, voice_provider=provider)
        subs = [
            s for s in service._read_local_subscribers()
            if s.get("active", True) and s.get("channel", "whatsapp") == "whatsapp"
        ]

    dispatched = []
    today = today_date_str()

    for sub in subs:
        area_id = sub.get("area_id")
        dest = sub.get("destination")
        if not area_id or not dest:
            continue

        if is_alert_already_sent(dest, area_id, "morning_briefing", today):
            log.info("[MORNING] Briefing duplicate suppressed for %s", dest)
            continue

        data = load_forecast_for_area(area_id)
        if not data or "forecast" not in data:
            continue

        content = build_morning_briefing(data["forecast"], sub, voice_provider=provider)
        if content["audio_bytes"]:
            backend.send_voice(dest, content["audio_bytes"], caption=content["text"], is_ptt=True)
        backend.send_text(dest, content["text"])

        record_row = {
            "area_id": area_id,
            "area_name": data["forecast"].get("name_en", area_id),
            "district": data["forecast"].get("district_en", ""),
            "severity": "info",
            "risk_event": "morning_briefing",
            "destination": normalize_phone(dest),
            "lang": sub.get("lang", "kn"),
            "channel": "whatsapp",
            "provider": "whatsapp",
            "status": "sent",
            "message": content["text"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        store.record(record_row)
        dispatched.append(record_row)

    return dispatched
