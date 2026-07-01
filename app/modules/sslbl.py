"""
modules/sslbl.py
================
Check an IP against abuse.ch's SSL Botnet C2 IP blacklist (SSLBL, no key). These
are IPs seen serving TLS certificates used by malware command-and-control. A hit
is a strong "this host is malicious" signal.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_text, resolve_ip


class SslblModule(BaseModule):
    key = "sslbl"
    name = "SSL botnet C2 (SSLBL)"
    category = Category.INTEL
    subtitle = "Malware C2 TLS blacklist"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    description = (
        "Checks an IP against abuse.ch SSLBL — IPs serving TLS certs tied to "
        "malware command-and-control. Public reputation data, no key."
    )

    async def run(self, value: str, ctx: RunContext):
        ip = await resolve_ip(value.strip())
        if not ip:
            return self.result(error=f"Could not resolve '{value}'.")
        try:
            csv = await fetch_text(ctx, "https://sslbl.abuse.ch/blacklist/sslipblacklist.csv",
                                   ttl=10800, namespace="sslbl")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"SSLBL fetch failed: {exc}")

        hit_line = None
        count = 0
        for line in csv.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            count += 1
            # format: Firstseen,DstIP,DstPort
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip() == ip:
                hit_line = line
                break

        listed = hit_line is not None
        findings = [{
            "label": "SSLBL", "confidence": "high" if listed else "info",
            "summary": (f"⚠ {ip} is a known malware C2 (SSLBL)" if listed
                        else f"{ip} not on the SSLBL C2 list"),
        }, {"label": "Entries checked", "summary": f"{count:,}"}]
        if hit_line:
            findings.append({"label": "Record", "summary": hit_line})
        return self.result(
            confidence=Confidence.HIGH if listed else Confidence.INFO,
            findings=findings, source_url="https://sslbl.abuse.ch/blacklist/",
            raw={"listed": listed},
            nodes=[GraphNode("ip", ip, props={"sslbl_c2": listed})],
        )
