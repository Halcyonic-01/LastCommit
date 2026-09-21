"""Notification dispatcher after recommendation generation."""

from .providers import get_provider
from .store import create_notification, update_notification


def format_message(payload):
    recommendation = payload["recommendation"]
    return "\n".join([
        "VarshaDrishti weather alert",
        f"Farmer: {payload['farmer']['name']}",
        f"Location: {payload['farmer']['location']}",
        f"Crop: {payload['crop']}",
        f"Risk: {payload['risk_level'].upper()}",
        f"Recommendation: {recommendation['action_en']}",
        "This is a forecast-based advisory. Please verify local conditions.",
    ])


def dispatch(payload):
    farmer = payload.get("farmer") or {}
    if not isinstance(farmer, dict) or not isinstance(farmer.get("name"), str) or len(farmer["name"].strip()) < 2:
        raise ValueError("farmer.name must contain at least 2 characters")
    if not isinstance(farmer.get("location"), str) or not farmer["location"].strip():
        raise ValueError("farmer.location is required")
    if payload.get("crop") not in {"ragi", "groundnut", "foxtail_millet", "horse_gram", "cotton", "maize"}:
        raise ValueError("crop is invalid")
    if payload.get("risk_level") not in {"high", "caution", "ok"}:
        raise ValueError("risk_level is invalid")
    recommendation = payload.get("recommendation") or {}
    if not isinstance(recommendation.get("action_en"), str) or not recommendation["action_en"].strip():
        raise ValueError("recommendation.action_en is required")
    provider = get_provider(payload.get("channel", "whatsapp"))
    message = format_message(payload)
    record, duplicate = create_notification({
        "idempotency_key": payload.get("idempotency_key"),
        "farmer": farmer,
        "crop": payload["crop"],
        "risk_level": payload["risk_level"],
        "recommendation": payload["recommendation"],
        "channel": provider.name,
        "channel_mode": provider.mode,
        "message": message,
        "status": "queued",
    })
    if duplicate:
        return record, True
    result = provider.send(recipient=payload["farmer"].get("phone", ""), message=message)
    record = update_notification(record["id"], result.status, result.detail)
    return record, False
