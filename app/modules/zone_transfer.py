"""
modules/zone_transfer.py
========================
Test a domain's nameservers for the classic DNS zone-transfer (AXFR)
misconfiguration. A correctly-configured server refuses AXFR from strangers; one
that allows it will hand over its ENTIRE zone — every record — a serious
information leak. We ask each nameserver for a transfer and report which (if any)
allow it, plus a sample of what leaked.

A single AXFR query per nameserver — a standard config test, not exploitation.
"""

from __future__ import annotations

import asyncio

import dns.resolver
import dns.query
import dns.zone

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)


def _nameservers(domain: str) -> list[str]:
    try:
        r = dns.resolver.Resolver(); r.lifetime = 5.0
        return [str(x.target).rstrip(".") for x in r.resolve(domain, "NS")]
    except Exception:
        return []


def _try_axfr(ns: str, domain: str) -> tuple[bool, int, list[str]]:
    try:
        xfr = dns.query.xfr(ns, domain, lifetime=8.0)
        zone = dns.zone.from_xfr(xfr)
        names = [str(n) for n in zone.nodes.keys()]
        return True, len(names), names[:15]
    except Exception:
        return False, 0, []


class ZoneTransferModule(BaseModule):
    key = "zone_transfer"
    name = "Zone transfer (AXFR)"
    category = Category.INFRASTRUCTURE
    subtitle = "Test for open AXFR leak"
    accepts = (InputType.DOMAIN,)
    needs_network = True
    description = (
        "Tests each nameserver for the AXFR zone-transfer misconfiguration — an "
        "open one leaks the entire DNS zone. Standard config test."
    )

    async def run(self, value: str, ctx: RunContext):
        domain = value.lower().strip().lstrip("*.")
        loop = asyncio.get_running_loop()
        nss = await loop.run_in_executor(None, _nameservers, domain)
        if not nss:
            return self.result(error="No nameservers found for the domain.")

        results = await asyncio.gather(
            *(loop.run_in_executor(None, _try_axfr, ns, domain) for ns in nss))

        vulnerable = []
        sample = []
        for ns, (ok, count, names) in zip(nss, results):
            if ok:
                vulnerable.append(f"{ns} — leaked {count} records")
                sample = names or sample

        findings = [
            {"label": "Nameservers tested", "values": nss},
        ]
        if vulnerable:
            findings.append({"label": "⚠ AXFR OPEN — zone leaked",
                             "summary": f"{len(vulnerable)} nameserver(s) allow transfer!",
                             "values": vulnerable, "confidence": "high"})
            if sample:
                findings.append({"label": "Sample records", "values": sample})
        else:
            findings.append({"label": "AXFR",
                             "summary": "All nameservers correctly refuse zone "
                                        "transfer — good.", "confidence": "info"})

        nodes = [GraphNode("domain", domain)]
        edges: list[GraphEdge] = []
        for ns in nss:
            nodes.append(GraphNode("host", ns, label=ns))
            edges.append(GraphEdge(f"domain:{domain}", f"host:{ns}", "hosted_on"))
        return self.result(
            confidence=Confidence.HIGH if vulnerable else Confidence.INFO,
            findings=findings, raw={"vulnerable": vulnerable}, nodes=nodes, edges=edges,
        )
