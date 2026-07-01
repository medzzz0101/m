"""
modules/dns_hostsearch.py
=========================
A second, independent subdomain source: HackerTarget's hostsearch dataset (no
key, rate-limited). It returns known subdomains WITH the IP each resolves to, so
it complements the CT-log (`subdomains`) and DNS-brute (`subdomain_brute`)
sources — the more sources, the fuller the attack-surface map.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_text


class DnsHostsearchModule(BaseModule):
    key = "dns_hostsearch"
    name = "Subdomains (hostsearch)"
    category = Category.INFRASTRUCTURE
    subtitle = "Extra subdomain source + IPs"
    accepts = (InputType.DOMAIN,)
    needs_network = True
    description = (
        "Additional subdomain discovery via HackerTarget's hostsearch dataset, "
        "returning each subdomain with the IP it resolves to."
    )

    async def run(self, value: str, ctx: RunContext):
        domain = value.lower().strip().lstrip("*.")
        url = f"https://api.hackertarget.com/hostsearch/?q={domain}"
        try:
            text = await fetch_text(ctx, url, ttl=43200, namespace="hostsearch")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"hostsearch failed: {exc}", source_url=url)

        low = text.lower()
        if "api count exceeded" in low or ("error" in low and "," not in text):
            return self.result(
                findings=[{"label": "hostsearch",
                           "summary": "Rate limit reached — try again later."}],
                confidence=Confidence.INFO, source_url=url)

        pairs = []
        for line in text.splitlines():
            if "," in line:
                host, ip = line.split(",", 1)
                pairs.append((host.strip().lower(), ip.strip()))

        nodes = [GraphNode("domain", domain)]
        edges: list[GraphEdge] = []
        for host, ip in pairs[:300]:
            if host == domain:
                continue
            nodes.append(GraphNode("subdomain", host, props={"ip": ip}))
            edges.append(GraphEdge(f"domain:{domain}", f"subdomain:{host}", "has_subdomain"))
            nodes.append(GraphNode("ip", ip))
            edges.append(GraphEdge(f"subdomain:{host}", f"ip:{ip}", "resolves_to"))

        findings = [{
            "label": "Subdomains", "summary": f"{len(pairs)} host(s) found",
            "values": [f"{h} → {ip}" for h, ip in pairs[:200]] or ["none found"],
            "confidence": "high" if pairs else "info",
        }]
        return self.result(
            confidence=Confidence.HIGH if pairs else Confidence.INFO,
            findings=findings, source_url=url,
            raw={"count": len(pairs), "hosts": pairs[:300]}, nodes=nodes, edges=edges,
        )
