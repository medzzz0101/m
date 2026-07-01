"""
modules/mac_lookup.py
=====================
Map a MAC address to the hardware manufacturer that owns its OUI (the first three
octets, assigned by the IEEE). Handy for identifying what KIND of device a MAC
belongs to (Apple, Cisco, a specific IoT vendor…). Also reports the locally-
administered / multicast bits, which reveal randomised (privacy) MACs.

Vendor lookup uses macvendors.com's free API (no key). Device metadata only —
a MAC identifies hardware, not a person.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_text


class MacLookupModule(BaseModule):
    key = "mac_lookup"
    name = "MAC vendor lookup"
    category = Category.INFRASTRUCTURE
    subtitle = "OUI → hardware manufacturer"
    accepts = (InputType.MAC,)
    needs_network = True
    description = (
        "Resolves a MAC address OUI to its hardware manufacturer (IEEE), and flags "
        "locally-administered / randomised MACs. Device metadata only."
    )

    async def run(self, value: str, ctx: RunContext):
        mac = value.strip().upper().replace("-", ":")
        hexdigits = mac.replace(":", "")
        if len(hexdigits) < 12:
            return self.result(error="Not a full MAC address.")

        # Local/multicast bits live in the first octet.
        first = int(hexdigits[0:2], 16)
        locally_admin = bool(first & 0b10)
        multicast = bool(first & 0b01)

        try:
            vendor = await fetch_text(ctx, f"https://api.macvendors.com/{mac}",
                                      ttl=604800, namespace="macvendor")
            vendor = vendor.strip()
        except Exception:
            vendor = None

        findings = [
            {"label": "MAC", "summary": mac},
            {"label": "OUI", "summary": mac[:8]},
            {"label": "Manufacturer",
             "summary": vendor or "not found (may be randomised/private)",
             "confidence": "high" if vendor else "info"},
            {"label": "Locally administered",
             "summary": "yes — likely a RANDOMISED/privacy MAC" if locally_admin else "no",
             "confidence": "info"},
            {"label": "Multicast", "summary": "yes" if multicast else "no"},
        ]
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if vendor else Confidence.INFO,
            source_url=f"https://macvendors.com/query/{mac}",
            raw={"mac": mac, "vendor": vendor, "locally_administered": locally_admin},
            nodes=[GraphNode("tech", vendor or mac, label=vendor or mac)],
        )
