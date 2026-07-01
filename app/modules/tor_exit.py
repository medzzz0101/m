"""
modules/tor_exit.py
===================
Check whether an IP is a known Tor EXIT node, using the Tor Project's public bulk
exit list (no key). Traffic arriving from a Tor exit is anonymised — useful
context when triaging who connected to your infrastructure.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_text, resolve_ip


class TorExitModule(BaseModule):
    key = "tor_exit"
    name = "Tor exit check"
    category = Category.INTEL
    subtitle = "Is the IP a Tor exit node?"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    description = (
        "Checks an IP against the Tor Project's public exit-node list. Traffic from "
        "a Tor exit is anonymised."
    )

    async def run(self, value: str, ctx: RunContext):
        ip = await resolve_ip(value.strip())
        if not ip:
            return self.result(error=f"Could not resolve '{value}'.")
        try:
            text = await fetch_text(ctx, "https://check.torproject.org/torbulkexitlist",
                                    ttl=3600, namespace="tor")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Tor list fetch failed: {exc}")

        exits = set(text.split())
        is_exit = ip in exits
        findings = [{
            "label": "Tor exit node",
            "summary": f"YES — {ip} is a Tor exit" if is_exit
                       else f"No — {ip} is not a Tor exit",
            "confidence": "high" if is_exit else "info",
        }, {"label": "List size", "summary": f"{len(exits):,} exit nodes checked"}]
        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if is_exit else Confidence.INFO,
            source_url="https://metrics.torproject.org/",
            raw={"is_exit": is_exit},
            nodes=[GraphNode("ip", ip, props={"tor_exit": is_exit})],
        )
