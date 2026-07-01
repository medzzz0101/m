"""
modules/typosquat.py
====================
Defensive anti-phishing: generate look-alike ("typosquat") variants of a domain
and check which ones are actually REGISTERED (resolve in DNS). Attackers register
these to impersonate a brand; defenders monitor them. We only resolve DNS for the
generated names — no contact, no scanning.

Techniques: character omission, duplication, adjacent-key swaps, common TLD
swaps, and hyphenation. A compact, readable subset of what dnstwist does.
"""

from __future__ import annotations

import asyncio

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import resolve_ip

ALT_TLDS = ["com", "net", "org", "co", "io", "info", "app", "online", "site", "xyz"]
KEYBOARD = {
    "a": "sqzw", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wrsdf",
    "i": "uojk", "l": "kop", "m": "njk", "n": "bhjm", "o": "iplk",
    "r": "etdf", "s": "awedxz", "t": "rygf", "u": "yhji",
}


def _variants(domain: str) -> set[str]:
    """Generate look-alike domains (bounded set)."""
    parts = domain.split(".")
    name, tld = parts[0], ".".join(parts[1:])
    out: set[str] = set()

    # Omission (drop one char).
    for i in range(len(name)):
        out.add(name[:i] + name[i + 1:] + "." + tld)
    # Duplication (double one char).
    for i in range(len(name)):
        out.add(name[:i] + name[i] + name[i:] + "." + tld)
    # Adjacent transposition (swap neighbours).
    for i in range(len(name) - 1):
        out.add(name[:i] + name[i + 1] + name[i] + name[i + 2:] + "." + tld)
    # Keyboard replacement.
    for i, ch in enumerate(name):
        for rep in KEYBOARD.get(ch, ""):
            out.add(name[:i] + rep + name[i + 1:] + "." + tld)
    # Hyphenation.
    for i in range(1, len(name)):
        out.add(name[:i] + "-" + name[i:] + "." + tld)
    # TLD swap.
    for t in ALT_TLDS:
        if t != tld:
            out.add(name + "." + t)

    out.discard(domain)
    # Keep it polite: cap the number of DNS lookups.
    return set(list(out)[:120])


class TyposquatModule(BaseModule):
    key = "typosquat"
    name = "Typosquat watch"
    category = Category.INFRASTRUCTURE
    subtitle = "Registered look-alike domains"
    accepts = (InputType.DOMAIN,)
    needs_network = True
    description = (
        "Generates look-alike domains (omission, duplication, key-swap, TLD swap, "
        "hyphenation) and reports which are actually REGISTERED — defensive "
        "anti-phishing monitoring. Resolves DNS only."
    )

    async def run(self, value: str, ctx: RunContext):
        domain = value.lower().strip().lstrip("*.")
        if "." not in domain:
            return self.result(error="Provide a domain (e.g. example.com).")

        variants = _variants(domain)
        # Resolve them all concurrently; a variant that resolves is "live".
        resolved = await asyncio.gather(*(resolve_ip(v) for v in variants))
        live = sorted([(v, ip) for v, ip in zip(variants, resolved) if ip])

        findings = [
            {"label": "Generated", "summary": f"{len(variants)} look-alike variants",
             "confidence": "info"},
            {"label": "Registered / live",
             "summary": f"{len(live)} resolve in DNS — potential impersonation",
             "values": [f"{v} → {ip}" for v, ip in live] or ["none live"],
             "confidence": "medium" if live else "info"},
        ]

        nodes = [GraphNode("domain", domain)]
        edges: list[GraphEdge] = []
        for v, ip in live:
            nodes.append(GraphNode("domain", v, props={"typosquat_of": domain, "ip": ip}))
            edges.append(GraphEdge(f"domain:{domain}", f"domain:{v}", "related_to",
                                   props={"kind": "typosquat"}))
        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if live else Confidence.INFO,
            raw={"generated": len(variants), "live": live}, nodes=nodes, edges=edges,
        )
