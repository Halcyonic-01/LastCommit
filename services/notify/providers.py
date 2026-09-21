"""One send() per channel, and an honest answer about whether the send was real.

`inapp` is the real delivery path: the officer sends, and the message appears on the
farmer's own notification page inside the PWA. It costs nothing, needs no phone number,
and is not simulated.

The metered outside channels sit behind the same interface. `simulated` is a property
of the provider, not a flag a caller can set — a simulated send cannot report itself as
a real one, and the dispatcher stores whatever the provider says. WhatsApp Cloud API is
metered, so the WhatsApp channel resolves to SimulatedWhatsApp until the two Meta
credentials in .env.example are set; the day they are, provider_for("whatsapp") returns
the real one and nothing upstream — rules engine, pipeline, dispatcher — changes.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from varshadrishti.data import supabase_client as SB  # noqa: E402


def _load(name: str, path: Path):
    """services/*/send.py all share the basename 'send' — load each by path."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Telegram and WhatsApp both render *bold* and _italic_; a plain handset does not, so a
# literal *ಮಳೆ* reads as broken text rather than emphasis. SMS gets the markers stripped.
_MARKUP = re.compile(r"[*_]")


def plain_text(text: str) -> str:
    return _MARKUP.sub("", text)


@dataclass(frozen=True)
class Result:
    ok: bool
    simulated: bool
    provider_message_id: str | None = None
    error: str | None = None


class SimulatedWhatsApp:
    """Composes and returns exactly what a real send would, and sends nothing.

    Deliberately NOT a delivery receipt: ok=True here means "the message was composed
    and would have been accepted", never "a farmer received a WhatsApp message". The
    `sim-` id prefix is there so a simulated id can never be mistaken for a Meta wamid.
    """

    key = "whatsapp"
    label = "WhatsApp (simulated)"
    simulated = True

    def configured(self) -> bool:
        return True  # nothing to configure — that is the whole point

    def send(self, destination: str, text: str) -> Result:
        if not destination:
            return Result(ok=False, simulated=True, error="no destination")
        return Result(ok=True, simulated=True, provider_message_id=f"sim-{uuid.uuid4().hex[:16]}")


class SimulatedSMS:
    """SMS with the markup stripped, transmitted nowhere.

    `sms` is a real channel in schema/supabase.sql and the onboarding screen registers
    real numbers against it, so the console has to be able to address it. Every Indian
    SMS gateway is metered, so this composes and records exactly what a gateway would
    be handed — swap in a gateway provider beside it and nothing upstream changes.
    """

    key = "sms"
    label = "SMS (simulated)"
    simulated = True

    def configured(self) -> bool:
        return True

    def send(self, destination: str, text: str) -> Result:
        if not destination:
            return Result(ok=False, simulated=True, error="no destination")
        return Result(ok=True, simulated=True, provider_message_id=f"sim-{uuid.uuid4().hex[:16]}")

    def compose(self, text: str) -> str:
        return plain_text(text)


class InApp:
    """The farmer's own notification page. The only channel here that really delivers.

    Area-addressed, not phone-addressed: the message is written once against the area
    and every farmer whose app is set to that hobli reads it. Nothing metered, nothing
    simulated, and no phone number involved — which is why it is the default.
    """

    key = "inapp"
    label = "Farmer app"
    simulated = False

    def configured(self) -> bool:
        return True  # the local fallback below means this channel always has somewhere to go

    def send(self, area_id: str, text: str, meta: dict | None = None) -> Result:
        if not area_id:
            return Result(ok=False, simulated=False, error="no area")
        m = meta or {}
        from . import store as ST  # noqa: PLC0415 — avoids a circular import at module load
        row, backend = ST.deliver_message({
            "area_id": area_id, "body": text,
            "severity": m.get("severity"), "rule_id": m.get("rule_id"),
            "source_table": m.get("source_table"), "risk_event": m.get("risk_event"),
            "risk_lead": m.get("risk_lead"), "risk_p": m.get("risk_p"),
        })
        # Delivered either way, but say which: Supabase reaches a real phone anywhere,
        # the file only reaches an app talking to this machine's broadcast server.
        return Result(ok=True, simulated=False, provider_message_id=row.get("id"),
                      error=None if backend == "supabase"
                      else "stored locally — reaches the app on this machine; "
                           "run schema/supabase.sql for real devices")


class WhatsAppCloud:
    """The real Meta Cloud API, reusing services/whatsapp/send.py's own call()."""

    key = "whatsapp"
    label = "WhatsApp Cloud API"
    simulated = False

    def __init__(self):
        self._wa = None

    def configured(self) -> bool:
        return bool(os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
                    and os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip())

    def send(self, destination: str, text: str) -> Result:
        if not self.configured():
            return Result(ok=False, simulated=False,
                          error="WHATSAPP_PHONE_NUMBER_ID/WHATSAPP_ACCESS_TOKEN not set")
        if self._wa is None:
            self._wa = _load("notify_whatsapp", ROOT / "services" / "whatsapp" / "send.py")
        payload = {"messaging_product": "whatsapp", "to": destination, "type": "text",
                   "text": {"body": text, "preview_url": False}}
        r = self._wa.call(os.environ["WHATSAPP_PHONE_NUMBER_ID"].strip(),
                          os.environ["WHATSAPP_ACCESS_TOKEN"].strip(), payload)
        if r.get("messages"):
            return Result(ok=True, simulated=False, provider_message_id=r["messages"][0].get("id"))
        err = r.get("error", {})
        return Result(ok=False, simulated=False,
                      error=err.get("message") or str(r)[:200] or "unknown Cloud API error")



class Unsupported:
    """A channel the subscribers table accepts but this tree has no sender for.

    `sms` is such a channel: schema/supabase.sql allows it and the onboarding screen
    registers it, but there is no services/sms/send.py. Failing loudly here is the
    honest outcome — those rows are real subscribers who are not being reached.
    """

    simulated = False

    def __init__(self, key: str):
        self.key = key
        self.label = f"{key} (no sender implemented)"

    def configured(self) -> bool:
        return False

    def send(self, destination: str, text: str) -> Result:
        return Result(ok=False, simulated=False,
                      error=f"no sender implemented for channel {self.key!r}")


def compose_for(provider, text: str) -> str:
    """The text this provider should actually be handed — most take it unchanged."""
    return provider.compose(text) if hasattr(provider, "compose") else text


def provider_for(channel: str):
    """The provider actually in force for a channel, right now, from the environment."""
    if channel == "inapp":
        return InApp()
    if channel == "whatsapp":
        real = WhatsAppCloud()
        return real if real.configured() else SimulatedWhatsApp()
    if channel == "sms":
        return SimulatedSMS()
    return Unsupported(channel)


# inapp first: it is the default and the only one that really delivers today.
CHANNELS = ("inapp", "whatsapp", "sms")
# Addressed by area rather than by a phone number — one message serves everyone there.
AREA_ADDRESSED = ("inapp",)


def channel_status() -> dict:
    """What the console shows before anyone presses send — label, simulated, ready."""
    out = {}
    for ch in CHANNELS:
        p = provider_for(ch)
        out[ch] = {"provider": p.label, "simulated": p.simulated, "configured": p.configured()}
    return out
