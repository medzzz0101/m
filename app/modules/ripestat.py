"""
modules/ripestat.py
===================
Authoritative routing / registry intelligence for an IP or ASN via RIPE NCC's
public RIPEstat API (no key). It answers "who runs this network, how is it routed,
and who do I report abuse to?":

  * network-info      -> the covering prefix and origin ASN(s)
  * abuse-contact     -> the network's PUBLISHED abuse-reporting address
  * (for an ASN) announced-prefixes -> how many prefixes it originates

The abuse contact is the address the network operator publishes for reports — a
public registry field about the NETWORK, not a private individual.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json, resolve_ip

RS = "https://stat.ripe.net/data"


class RipeStatModule(BaseModule):
    key = "ripestat"
    name = "RIPEstat routing"
    category = Category.INFRASTRUCTURE
    subtitle = "Prefix, ASN, abuse contact"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    description = (
        "Authoritative routing/registry data (RIPEstat): covering prefix, origin "
        "ASN, network abuse-reporting contact, and prefix count for the ASN."
    )

    async def run(self, value: str, ctx: RunContext):
        ip = await resolve_ip(value.strip())
        if not ip:
            return self.result(error=f"Could not resolve '{value}'.")

        findings = []
        nodes = [GraphNode("ip", ip)]
        edges: list[GraphEdge] = []
        raw = {}

        try:
            ni = await fetch_json(ctx, f"{RS}/network-info/data.json?resource={ip}",
                                  ttl=86400, namespace="ripe")
            d = ni.get("data", {})
            prefix = d.get("prefix")
            asns = d.get("asns", []) or []
            raw["network"] = d
            if prefix:
                findings.append({"label": "Covering prefix", "summary": prefix})
                nodes.append(GraphNode("asn", prefix, label=prefix))
                edges.append(GraphEdge(f"ip:{ip}", f"asn:{prefix}", "hosted_on"))
            if asns:
                findings.append({"label": "Origin ASN", "summary": ", ".join(f"AS{a}" for a in asns)})
        except Exception:
            pass

        try:
            ac = await fetch_json(ctx, f"{RS}/abuse-contact-finder/data.json?resource={ip}",
                                  ttl=86400, namespace="ripe")
            contacts = ac.get("data", {}).get("abuse_contacts", []) or []
            raw["abuse"] = contacts
            findings.append({"label": "Abuse contact",
                             "summary": ", ".join(contacts) or "not published",
                             "confidence": "high" if contacts else "info"})
            for c in contacts:
                nodes.append(GraphNode("email", c))
                edges.append(GraphEdge(f"ip:{ip}", f"email:{c}", "related_to",
                                       props={"role": "abuse-contact"}))
        except Exception:
            pass

        # If the input was an ASN-bearing thing, add prefix count for the ASN.
        m = re.search(r"AS?(\d+)", value.upper())
        asn = m.group(1) if m else (str(asns[0]) if 'asns' in dir() and asns else None)
        try:
            if asn:
                ap = await fetch_json(
                    ctx, f"{RS}/announced-prefixes/data.json?resource=AS{asn}",
                    ttl=86400, namespace="ripe")
                pfx = ap.get("data", {}).get("prefixes", []) or []
                findings.append({"label": f"AS{asn} announces", "summary": f"{len(pfx)} prefixes"})
        except Exception:
            pass

        return self.result(
            findings=findings or [{"label": "RIPEstat", "summary": "no data"}],
            confidence=Confidence.HIGH if findings else Confidence.INFO,
            source_url=f"https://stat.ripe.net/{ip}", raw=raw, nodes=nodes, edges=edges,
        )
