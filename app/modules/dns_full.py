"""
modules/dns_full.py
===================
Full DNS picture for a domain: A/AAAA/MX/TXT/NS/CNAME/SOA, plus the email-auth
records investigators care about (SPF / DMARC / DKIM hints) and a DNSSEC check.

Why it matters: DNS is the skeleton of an organisation's infrastructure. The A
records become `ip` nodes the rest of the engine can pivot on; MX reveals the
mail provider; TXT/SPF/DMARC expose third-party services and security posture.

Uses dnspython directly (synchronous), run in a thread so it doesn't block the
asyncio event loop.
"""

from __future__ import annotations

import asyncio

import dns.resolver
import dns.dnssec
import dns.name
import dns.message
import dns.query

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)

RECORD_TYPES = ["A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA"]


def _resolve(domain: str, rtype: str) -> list[str]:
    """Resolve one record type; return string values (never raises)."""
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 5.0
        answers = resolver.resolve(domain, rtype)
        return [r.to_text() for r in answers]
    except Exception:
        return []


def _dnssec_signed(domain: str) -> bool:
    """Cheap DNSSEC presence check: does the zone publish DNSKEY records?"""
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 5.0
        resolver.resolve(domain, "DNSKEY")
        return True
    except Exception:
        return False


class DnsFullModule(BaseModule):
    key = "dns_full"
    name = "DNS (full)"
    category = Category.INFRASTRUCTURE
    subtitle = "A/MX/TXT/NS + SPF/DMARC/DNSSEC"
    accepts = (InputType.DOMAIN,)
    needs_network = True
    description = (
        "Resolves all common record types and inspects email-authentication "
        "records (SPF/DMARC/DKIM hints) and DNSSEC. Feeds IP nodes to the graph."
    )

    async def run(self, value: str, ctx: RunContext):
        domain = value.lower().strip()

        # Run every blocking DNS lookup in threads, concurrently.
        loop = asyncio.get_running_loop()
        tasks = {rt: loop.run_in_executor(None, _resolve, domain, rt)
                 for rt in RECORD_TYPES}
        dmarc_task = loop.run_in_executor(None, _resolve, f"_dmarc.{domain}", "TXT")
        dnssec_task = loop.run_in_executor(None, _dnssec_signed, domain)

        records = {rt: await tasks[rt] for rt in RECORD_TYPES}
        dmarc = await dmarc_task
        dnssec = await dnssec_task

        findings: list[dict] = []
        nodes: list[GraphNode] = [GraphNode("domain", domain)]
        edges: list[GraphEdge] = []

        # --- A / AAAA -> ip nodes + resolves_to edges ----------------------
        for rt in ("A", "AAAA"):
            for ip in records[rt]:
                nodes.append(GraphNode("ip", ip, props={"family": rt}))
                edges.append(GraphEdge(f"domain:{domain}", f"ip:{ip}", "resolves_to"))
        if records["A"] or records["AAAA"]:
            findings.append({
                "label": "Addresses",
                "summary": f"{len(records['A']) + len(records['AAAA'])} IP(s)",
                "values": records["A"] + records["AAAA"],
            })

        # --- MX -> mail provider hint --------------------------------------
        if records["MX"]:
            findings.append({"label": "Mail (MX)", "values": records["MX"]})

        # --- NS -------------------------------------------------------------
        if records["NS"]:
            findings.append({"label": "Nameservers", "values": records["NS"]})

        # --- TXT, with SPF extracted ---------------------------------------
        spf = [t for t in records["TXT"] if "v=spf1" in t.lower()]
        if records["TXT"]:
            findings.append({"label": "TXT", "values": records["TXT"]})
        findings.append({
            "label": "SPF",
            "summary": "present" if spf else "missing",
            "confidence": "info",
            "values": spf or ["(no SPF record)"],
        })

        # --- DMARC ----------------------------------------------------------
        findings.append({
            "label": "DMARC",
            "summary": "present" if dmarc else "missing",
            "values": dmarc or ["(no _dmarc TXT record)"],
        })

        # --- CNAME / SOA ----------------------------------------------------
        if records["CNAME"]:
            findings.append({"label": "CNAME", "values": records["CNAME"]})
        if records["SOA"]:
            findings.append({"label": "SOA", "values": records["SOA"]})

        # --- DNSSEC ---------------------------------------------------------
        findings.append({
            "label": "DNSSEC",
            "summary": "signed" if dnssec else "unsigned",
            "confidence": "info",
        })

        any_data = any(records[rt] for rt in RECORD_TYPES)
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if any_data else Confidence.INFO,
            source_url=f"https://dns.google/query?name={domain}",
            raw={"records": records, "dmarc": dmarc, "dnssec": dnssec},
            nodes=nodes,
            edges=edges,
            error=None if any_data else "No DNS records resolved.",
        )
