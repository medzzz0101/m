"""
modules/subdomains.py
=====================
Subdomain discovery from Certificate Transparency logs. Every TLS certificate a
CA issues is logged publicly; by reading those logs we learn the hostnames an
organisation has requested certs for — a classic, entirely passive way to map
attack surface.

Primary source: certspotter (https://api.certspotter.com, no key, rate-limited).
crt.sh is a common alternative but is frequently slow/unreachable, so we lead
with certspotter and keep crt.sh as a soft fallback.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


class SubdomainsModule(BaseModule):
    key = "subdomains"
    name = "Subdomains (CT)"
    category = Category.INFRASTRUCTURE
    subtitle = "From certificate transparency"
    accepts = (InputType.DOMAIN,)
    needs_network = True
    description = (
        "Discovers subdomains from public Certificate Transparency logs "
        "(certspotter). Passive — no scanning of the target."
    )

    async def run(self, value: str, ctx: RunContext):
        domain = value.lower().strip().lstrip("*.")
        url = (f"https://api.certspotter.com/v1/issuances?domain={domain}"
               f"&include_subdomains=true&expand=dns_names")
        try:
            data = await fetch_json(ctx, url, ttl=21600, namespace="certspotter")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"CT lookup failed: {exc}", source_url=url)

        # Collect, dedupe, and drop wildcards.
        names: set[str] = set()
        for issuance in data or []:
            for name in issuance.get("dns_names", []):
                name = name.lower().lstrip("*.")
                if name.endswith(domain):
                    names.add(name)
        subs = sorted(names)

        nodes = [GraphNode("domain", domain)]
        edges: list[GraphEdge] = []
        for s in subs:
            if s == domain:
                continue
            nodes.append(GraphNode("subdomain", s))
            edges.append(GraphEdge(f"domain:{domain}", f"subdomain:{s}", "has_subdomain"))

        findings = [{
            "label": "Subdomains",
            "summary": f"{len([s for s in subs if s != domain])} unique found",
            "values": [s for s in subs if s != domain][:200] or ["none found"],
        }]
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if len(subs) > 1 else Confidence.INFO,
            source_url=f"https://crt.sh/?q=%25.{domain}", raw={"count": len(subs),
                                                               "subdomains": subs},
            nodes=nodes, edges=edges,
        )
