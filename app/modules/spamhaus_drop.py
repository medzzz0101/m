"""
modules/spamhaus_drop.py
========================
Check an IP against the Spamhaus DROP ("Don't Route Or Peer") list — netblocks
that Spamhaus has identified as controlled by threat actors / hijacked. If a
target's IP falls inside a DROP range it's a strong badness signal. Public list,
no key.
"""

from __future__ import annotations

import ipaddress

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_text, resolve_ip


class SpamhausDropModule(BaseModule):
    key = "spamhaus_drop"
    name = "Spamhaus DROP"
    category = Category.INTEL
    subtitle = "Hijacked / bad netblock check"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    description = (
        "Checks an IP against the Spamhaus DROP list of netblocks controlled by "
        "threat actors / hijacked. Public reputation data, no key."
    )

    async def run(self, value: str, ctx: RunContext):
        ip = await resolve_ip(value.strip())
        if not ip:
            return self.result(error=f"Could not resolve '{value}'.")
        try:
            text = await fetch_text(ctx, "https://www.spamhaus.org/drop/drop.txt",
                                    ttl=21600, namespace="drop")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"DROP list fetch failed: {exc}")

        addr = ipaddress.ip_address(ip)
        hit = None
        count = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            cidr = line.split(";")[0].strip()
            try:
                net = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                continue
            count += 1
            if addr in net:
                hit = cidr
                break

        findings = [{
            "label": "DROP list",
            "summary": (f"⚠ {ip} is inside HIJACKED/bad netblock {hit}" if hit
                        else f"{ip} is NOT on the Spamhaus DROP list"),
            "confidence": "high" if hit else "info",
        }, {"label": "Ranges checked", "summary": f"{count:,}"}]
        return self.result(
            confidence=Confidence.HIGH if hit else Confidence.INFO,
            findings=findings, source_url="https://www.spamhaus.org/drop/",
            raw={"hit": hit},
            nodes=[GraphNode("ip", ip, props={"spamhaus_drop": bool(hit)})],
        )
