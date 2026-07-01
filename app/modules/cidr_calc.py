"""
modules/cidr_calc.py
====================
A subnet / CIDR calculator. Give it a CIDR (e.g. 10.0.0.0/24) or an IP with a
mask and it returns the network address, broadcast, usable host range, host
count, netmask/wildcard and whether it's private/global. Handy when you're
reasoning about a netblock discovered by the ASN / reverse-IP modules.

Pure stdlib (ipaddress). Offline.
"""

from __future__ import annotations

import ipaddress

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)


class CidrCalcModule(BaseModule):
    key = "cidr_calc"
    name = "CIDR / subnet calc"
    category = Category.INFRASTRUCTURE
    subtitle = "Netblock math"
    accepts = (InputType.TEXT,)
    needs_network = False
    description = (
        "Subnet calculator: network/broadcast, usable host range, host count, "
        "netmask/wildcard and scope for a CIDR (e.g. 10.0.0.0/24). Offline."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        if "/" not in v:
            return self.result(error="Provide a CIDR, e.g. 192.168.1.0/24.")
        try:
            net = ipaddress.ip_network(v, strict=False)
        except ValueError as exc:
            return self.result(error=f"Invalid CIDR: {exc}")

        hosts = list(net.hosts())
        findings = [
            {"label": "Network", "summary": str(net.network_address)},
            {"label": "Prefix", "summary": f"/{net.prefixlen}"},
            {"label": "Netmask", "summary": str(net.netmask)},
            {"label": "Wildcard", "summary": str(net.hostmask)},
            {"label": "Total addresses", "summary": f"{net.num_addresses:,}"},
            {"label": "Usable hosts",
             "summary": f"{len(hosts):,}" +
             (f"  ({hosts[0]} – {hosts[-1]})" if hosts else "")},
        ]
        if net.version == 4 and net.num_addresses >= 2:
            findings.append({"label": "Broadcast", "summary": str(net.broadcast_address)})
        findings.append({"label": "Scope",
                         "summary": "private" if net.is_private else
                         ("global/public" if net.is_global else "special")})

        return self.result(
            findings=findings, confidence=Confidence.HIGH,
            raw={"network": str(net), "num": net.num_addresses},
            nodes=[GraphNode("asn", str(net), label=str(net))],
        )
