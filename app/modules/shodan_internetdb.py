"""
modules/shodan_internetdb.py
============================
PASSIVE attack-surface for an IP via Shodan's free InternetDB API
(https://internetdb.shodan.io/<ip>, no key). It returns what Shodan ALREADY
observed — open ports, detected software (CPEs), hostnames, tags and known CVEs
— WITHOUT us sending a single packet to the target. That's the difference
between this (passive OSINT) and the active `port_services` module.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json, resolve_ip


class ShodanInternetDbModule(BaseModule):
    key = "shodan_internetdb"
    name = "Exposure (Shodan)"
    category = Category.INFRASTRUCTURE
    subtitle = "Passive ports, CPEs, CVEs"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    description = (
        "Passive attack-surface from Shodan's free InternetDB: previously-observed "
        "open ports, software (CPEs), hostnames, tags and known CVEs — without "
        "sending any traffic to the target."
    )

    async def run(self, value: str, ctx: RunContext):
        ip = await resolve_ip(value.strip())
        if not ip:
            return self.result(error=f"Could not resolve '{value}' to an IP.")
        url = f"https://internetdb.shodan.io/{ip}"
        try:
            data = await fetch_json(ctx, url, ttl=21600, namespace="shodan")
        except Exception as exc:  # noqa: BLE001
            # 404 simply means "nothing on file" — report cleanly, not as a crash.
            if "404" in str(exc):
                return self.result(
                    findings=[{"label": "Exposure",
                               "summary": "No records in Shodan InternetDB."}],
                    confidence=Confidence.INFO, source_url=url)
            return self.result(error=f"InternetDB failed: {exc}", source_url=url)

        ports = data.get("ports", []) or []
        cpes = data.get("cpes", []) or []
        vulns = data.get("vulns", []) or []
        hostnames = data.get("hostnames", []) or []
        tags = data.get("tags", []) or []

        findings = [
            {"label": "Open ports", "summary": f"{len(ports)} observed",
             "values": [str(p) for p in ports] or ["none on file"]},
        ]
        if hostnames:
            findings.append({"label": "Hostnames", "values": hostnames})
        if cpes:
            findings.append({"label": "Software (CPEs)", "values": cpes})
        if tags:
            findings.append({"label": "Tags", "values": tags})
        if vulns:
            findings.append({"label": "Known CVEs",
                             "summary": f"{len(vulns)} — review carefully",
                             "values": vulns, "confidence": "high"})

        nodes = [GraphNode("ip", ip, props={"ports": ports, "vulns": vulns})]
        edges: list[GraphEdge] = []
        for cpe in cpes:
            nodes.append(GraphNode("tech", cpe, label=cpe.split(":")[-1] or cpe))
            edges.append(GraphEdge(f"ip:{ip}", f"tech:{cpe}", "runs_tech"))
        for h in hostnames:
            nodes.append(GraphNode("domain", h))
            edges.append(GraphEdge(f"domain:{h}", f"ip:{ip}", "resolves_to"))

        # Confidence reflects how interesting the surface is.
        conf = Confidence.HIGH if vulns else (
            Confidence.MEDIUM if ports else Confidence.INFO)
        return self.result(
            findings=findings, confidence=conf,
            source_url=f"https://www.shodan.io/host/{ip}", raw=data,
            nodes=nodes, edges=edges,
        )
