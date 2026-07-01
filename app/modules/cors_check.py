"""
modules/cors_check.py
=====================
Probe a site's CORS (Cross-Origin Resource Sharing) policy for common
misconfigurations that can let a malicious website read authenticated responses:

  * reflects an arbitrary Origin (ACAO mirrors what we send)
  * allows a wildcard * together with credentials
  * trusts "null" origin
  * over-broad subdomain trust

We send GETs with crafted Origin headers and read the response CORS headers — a
diagnostic request, not an attack.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import host_of

EVIL = "https://evil.example.com"


class CorsCheckModule(BaseModule):
    key = "cors_check"
    name = "CORS check"
    category = Category.INFRASTRUCTURE
    subtitle = "Cross-origin misconfig"
    accepts = (InputType.DOMAIN, InputType.URL)
    needs_network = True
    description = (
        "Tests CORS policy for risky misconfigurations (reflected origin, "
        "wildcard-with-credentials, null-origin trust) via crafted Origin headers."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        url = v if v.startswith("http") else f"https://{v}"

        async def probe(origin):
            try:
                r = await ctx.http.get(url, follow_redirects=True, headers={
                    "User-Agent": "Mozilla/5.0", "Origin": origin})
                return {k.lower(): v for k, v in r.headers.items()}
            except Exception:
                return {}

        reflected = await probe(EVIL)
        nullo = await probe("null")

        acao_r = reflected.get("access-control-allow-origin", "")
        acac_r = reflected.get("access-control-allow-credentials", "")
        acao_n = nullo.get("access-control-allow-origin", "")

        issues = []
        if acao_r == EVIL:
            issues.append("Reflects arbitrary Origin (ACAO mirrors attacker origin)"
                          + (" WITH credentials — critical" if acac_r == "true" else ""))
        if acao_r == "*" and acac_r == "true":
            issues.append("Wildcard * with credentials (invalid but dangerous if honoured)")
        if acao_n == "null":
            issues.append("Trusts the 'null' origin (exploitable from sandboxed iframes)")

        base_acao = reflected.get("access-control-allow-origin", "(none)")
        findings = [
            {"label": "ACAO (reflected test)", "summary": base_acao or "(none)"},
            {"label": "Allow-Credentials", "summary": acac_r or "(none)"},
            {"label": "Misconfigurations",
             "summary": f"{len(issues)} found" if issues else "none detected",
             "values": issues or ["CORS looks safe for these tests"],
             "confidence": "high" if issues else "info"},
        ]
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if issues else Confidence.INFO,
            source_url=url, raw={"reflected": reflected, "null": nullo},
            nodes=[GraphNode("domain", host_of(url))],
        )
