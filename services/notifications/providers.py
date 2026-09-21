"""Provider boundary: the demo provider can later be replaced by WhatsApp Cloud."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    status: str
    detail: str


class SimulatedWhatsAppProvider:
    name = "whatsapp"
    mode = "SIMULATED / DEMO"

    def send(self, *, recipient: str, message: str) -> ProviderResult:
        # No network call is made. The status is deliberately not "delivered".
        return ProviderResult(
            provider=self.name,
            status="simulated",
            detail=f"DEMO only: WhatsApp message prepared for {recipient or 'farmer'}; not sent",
        )


def get_provider(name: str):
    if name != "whatsapp":
        raise ValueError("Only the WhatsApp provider is enabled")
    return SimulatedWhatsAppProvider()
