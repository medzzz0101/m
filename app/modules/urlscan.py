"""
modules/urlscan.py
==================
Query urlscan.io's PUBLIC search API (no key) for prior scans of a domain. Each
scan is a snapshot someone already captured of a page — giving you historical
URLs, the IPs/ASNs pages resolved to, and related hostnames. It's a passive way
to see a domain's web footprint over time without touching it yourself.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


class UrlscanModule(BaseModule):
    key = "urlscan"
    name = "urlscan.io"
    category = Category.INFRASTRUCTURE
    subtitle = "Historical scans, IPs, links"
    accepts = (InputType.DOMAIN, InputType.URL, InputType.IP)
    needs_network = True
    description = (
        "Public urlscan.io search: prior scans of a domain — historical page URLs, "
        "the IPs/ASNs they resolved to and related hostnames. Passive."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip().lower()
        # domain: / ip: / page. urlscan supports field queries.
        if v.replace(".", "").isdigit():
            q = f"ip:{v}"
        else:
            host = v.split("/")[2] if v.startswith("http") else v
            q = f"domain:{host}"
        url = f"https://urlscan.io/api/v1/search/?q={q}&size=20"
        try:
            data = await fetch_json(ctx, url, ttl=21600, namespace="urlscan")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"urlscan search failed: {exc}", source_url=url)

        results = data.get("results", []) or []
        pages = []
        ips: set[str] = set()
        asns: set[str] = set()
        domains: set[str] = set()
        for r in results:
            page = r.get("page", {})
            if page.get("url"):
                pages.append(page["url"])
            if page.get("ip"):
                ips.add(page["ip"])
            if page.get("asnname"):
                asns.add(page["asnname"])
            if page.get("domain"):
                domains.add(page["domain"])

        findings = [
            {"label": "Scans found", "summary": f"{data.get('total', len(results))} "
             f"total (showing {len(results)})"},
        ]
        if ips:
            findings.append({"label": "IPs seen", "values": sorted(ips)})
        if asns:
            findings.append({"label": "Networks", "values": sorted(asns)})
        if pages:
            findings.append({"label": "Recent page URLs", "values": pages[:15]})

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        base_host = q.split(":", 1)[1]
        nodes.append(GraphNode("domain" if "domain" in q else "ip", base_host))
        for ip in ips:
            nodes.append(GraphNode("ip", ip))
            edges.append(GraphEdge(f"domain:{base_host}", f"ip:{ip}", "resolves_to"))

        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if results else Confidence.INFO,
            source_url=f"https://urlscan.io/search/#{q}",
            raw={"total": data.get("total"), "ips": sorted(ips),
                 "asns": sorted(asns), "pages": pages[:20]},
            nodes=nodes, edges=edges,
        )
