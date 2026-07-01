"""
modules/threat_feeds.py
=======================
Check an IP (or a domain's IP) against PUBLIC threat-intelligence feeds — is this
address known-bad? We use abuse.ch's Feodo Tracker (no key), a curated list of
botnet C2 (command-and-control) servers for families like Emotet, Dridex,
TrickBot and QakBot.

Reputation lookup against a public blocklist — nothing is sent to the target.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json, resolve_ip

FEODO = "https://feodotracker.abuse.ch/downloads/ipblocklist.json"


class ThreatFeedsModule(BaseModule):
    key = "threat_feeds"
    name = "Threat feeds"
    category = Category.INTEL
    subtitle = "Botnet C2 reputation (abuse.ch)"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    description = (
        "Checks an IP against abuse.ch Feodo Tracker's public botnet C2 blocklist "
        "(Emotet/Dridex/TrickBot/QakBot…). Public reputation data, no key."
    )

    async def run(self, value: str, ctx: RunContext):
        ip = await resolve_ip(value.strip())
        if not ip:
            return self.result(error=f"Could not resolve '{value}'.")
        try:
            feed = await fetch_json(ctx, FEODO, ttl=3600, namespace="feodo")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Feed fetch failed: {exc}", source_url=FEODO)

        match = next((e for e in feed if e.get("ip_address") == ip), None)
        if match:
            findings = [
                {"label": "⚠ Listed", "summary": f"{ip} is a known botnet C2",
                 "confidence": "high"},
                {"label": "Malware", "summary": match.get("malware", "?")},
                {"label": "Port", "summary": str(match.get("port", "?"))},
                {"label": "Status", "summary": match.get("status", "?")},
                {"label": "First seen", "summary": match.get("first_seen", "?")},
                {"label": "AS", "summary": f"AS{match.get('as_number','?')} "
                 f"{match.get('as_name','')}"},
            ]
            conf = Confidence.HIGH
        else:
            findings = [{"label": "Reputation",
                         "summary": f"{ip} is NOT on the Feodo C2 blocklist "
                                    f"({len(feed)} entries checked).",
                         "confidence": "info"}]
            conf = Confidence.INFO

        node = GraphNode("ip", ip, props={"c2": bool(match),
                                          "malware": match.get("malware") if match else None})
        return self.result(findings=findings, confidence=conf,
                           source_url="https://feodotracker.abuse.ch/browse/",
                           raw=match or {"listed": False}, nodes=[node])
