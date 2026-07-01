"""
modules/reverse_ip.py
=====================
"What other domains live on this IP?" Reverse-IP (a.k.a. virtual-host) lookup via
HackerTarget's free API (no key, rate-limited). Shared hosting means one IP often
serves many sites; finding the neighbours can reveal related properties or, on
dedicated infra, an organisation's other domains.

Passive: we query a public dataset, we don't scan the IP.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_text, resolve_ip


class ReverseIpModule(BaseModule):
    key = "reverse_ip"
    name = "Reverse IP"
    category = Category.INFRASTRUCTURE
    subtitle = "Other domains on this IP"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    description = (
        "Finds other domains hosted on the same IP (virtual hosts) via "
        "HackerTarget's public dataset. Reveals co-hosted / related sites."
    )

    async def run(self, value: str, ctx: RunContext):
        ip = await resolve_ip(value.strip())
        if not ip:
            return self.result(error=f"Could not resolve '{value}'.")
        url = f"https://api.hackertarget.com/reverseiplookup/?q={ip}"
        try:
            text = await fetch_text(ctx, url, ttl=43200, namespace="revip")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Reverse-IP lookup failed: {exc}",
                               source_url=url)

        # HackerTarget returns one host per line, or an error/limit message.
        low = text.lower()
        if "api count exceeded" in low or "error" in low and "\n" not in text.strip():
            return self.result(
                findings=[{"label": "Reverse IP",
                           "summary": "Rate limit reached on the free dataset — "
                                      "try again later."}],
                confidence=Confidence.INFO, source_url=url)

        domains = sorted({d.strip().lower() for d in text.splitlines()
                          if d.strip() and "." in d})

        nodes = [GraphNode("ip", ip)]
        edges: list[GraphEdge] = []
        for d in domains[:300]:
            nodes.append(GraphNode("domain", d))
            edges.append(GraphEdge(f"domain:{d}", f"ip:{ip}", "resolves_to"))

        findings = [{
            "label": "Co-hosted domains",
            "summary": f"{len(domains)} domain(s) on {ip}",
            "values": domains[:200] or ["none found"],
            "note": "Shared hosting can co-locate unrelated sites — corroborate "
                    "before assuming common ownership.",
        }]
        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if domains else Confidence.INFO,
            source_url=url, raw={"count": len(domains), "domains": domains},
            nodes=nodes, edges=edges,
        )
