"""
modules/caa_check.py
====================
Read a domain's CAA (Certification Authority Authorization) records. CAA tells
the world WHICH certificate authorities are allowed to issue certs for a domain —
a control against mis-issuance. Missing CAA means any CA may issue (weaker
posture); present CAA pins issuance to specific CAs and can declare an incident
reporting address.

Pure DNS lookup (dnspython). Offline of external APIs.
"""

from __future__ import annotations

import asyncio

import dns.resolver

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)


def _caa(domain: str) -> list[str]:
    try:
        r = dns.resolver.Resolver(); r.lifetime = 5.0
        return [x.to_text() for x in r.resolve(domain, "CAA")]
    except Exception:
        return []


class CaaCheckModule(BaseModule):
    key = "caa_check"
    name = "CAA records"
    category = Category.INFRASTRUCTURE
    subtitle = "Allowed cert authorities"
    accepts = (InputType.DOMAIN,)
    needs_network = True
    description = (
        "Reads a domain's CAA records — which CAs may issue its certificates and "
        "any incident-reporting address. Missing CAA = any CA may issue."
    )

    async def run(self, value: str, ctx: RunContext):
        domain = value.lower().strip().lstrip("*.")
        loop = asyncio.get_running_loop()
        records = await loop.run_in_executor(None, _caa, domain)

        issuers, iodef = [], []
        for rec in records:
            low = rec.lower()
            if "issue" in low:
                # e.g.  0 issue "letsencrypt.org"
                parts = rec.split('"')
                if len(parts) > 1:
                    issuers.append(parts[1])
            if "iodef" in low:
                parts = rec.split('"')
                if len(parts) > 1:
                    iodef.append(parts[1])

        if records:
            findings = [
                {"label": "CAA", "summary": f"{len(records)} record(s) — issuance "
                 "is restricted", "confidence": "high"},
                {"label": "Allowed CAs", "values": issuers or ["(issue records present)"]},
            ]
            if iodef:
                findings.append({"label": "Incident reporting (iodef)", "values": iodef})
        else:
            findings = [{"label": "CAA",
                         "summary": "No CAA records — ANY certificate authority may "
                                    "issue certs for this domain.",
                         "confidence": "medium"}]

        return self.result(
            confidence=Confidence.HIGH if records else Confidence.INFO,
            findings=findings, source_url=f"https://dns.google/query?name={domain}&type=CAA",
            raw={"records": records}, nodes=[GraphNode("domain", domain)],
        )
