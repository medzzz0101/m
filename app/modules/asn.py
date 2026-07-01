"""
modules/asn.py
==============
Network ownership for an IP via RDAP (rdap.org/ip/<ip>, no key). RDAP returns the
registered network block — the allocation name, the owning organisation, the CIDR
range and the country. This tells you WHO runs the network an asset sits on
(hosting provider, cloud, enterprise) — the "asn / network owner" piece.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json, resolve_ip


class AsnModule(BaseModule):
    key = "asn"
    name = "Network owner (RDAP)"
    category = Category.INFRASTRUCTURE
    subtitle = "Allocation, range, country"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    description = (
        "Registered network block for an IP via RDAP: allocation name, owning "
        "organisation, CIDR range and country."
    )

    async def run(self, value: str, ctx: RunContext):
        ip = await resolve_ip(value.strip())
        if not ip:
            return self.result(error=f"Could not resolve '{value}' to an IP.")
        url = f"https://rdap.org/ip/{ip}"
        try:
            data = await fetch_json(ctx, url, ttl=86400, namespace="rdap_ip",
                                    follow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"RDAP IP lookup failed: {exc}", source_url=url)

        name = data.get("name")
        handle = data.get("handle")
        country = data.get("country")
        start, end = data.get("startAddress"), data.get("endAddress")
        cidrs = [f"{c.get('v4prefix') or c.get('v6prefix')}/{c.get('length')}"
                 for c in data.get("cidr0_cidrs", []) or []
                 if c.get("length") is not None]

        # Owning org from entities.
        org = None
        for ent in data.get("entities", []) or []:
            vcard = ent.get("vcardArray")
            if vcard and len(vcard) > 1:
                for item in vcard[1]:
                    if item and item[0] == "fn":
                        org = item[3]
                        break
            if org:
                break

        findings = [
            {"label": "Allocation", "summary": name or "—"},
            {"label": "Handle / range", "summary": handle or f"{start} – {end}"},
            {"label": "Organisation", "summary": org or "—"},
            {"label": "Country", "summary": country or "—"},
        ]
        if cidrs:
            findings.append({"label": "CIDR", "values": cidrs})

        nodes = [GraphNode("ip", ip)]
        edges: list[GraphEdge] = []
        net_id = handle or name or "network"
        nodes.append(GraphNode("asn", net_id, label=name or handle,
                               props={"org": org, "country": country}))
        edges.append(GraphEdge(f"ip:{ip}", f"asn:{net_id}", "hosted_on"))
        if org:
            nodes.append(GraphNode("org", org, label=org))
            edges.append(GraphEdge(f"asn:{net_id}", f"org:{org}", "same_owner"))

        return self.result(
            findings=findings, confidence=Confidence.HIGH,
            source_url=url, raw=data, nodes=nodes, edges=edges,
        )
