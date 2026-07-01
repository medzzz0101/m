"""
modules/http_methods.py
=======================
Ask a web server which HTTP methods it allows (via an OPTIONS request and the
Allow header) and flag risky ones — PUT/DELETE (content tampering), TRACE (Cross-
Site Tracing), CONNECT, PATCH. A single OPTIONS request; we never actually invoke
the dangerous methods.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import host_of

RISKY = {"PUT", "DELETE", "TRACE", "CONNECT", "PATCH"}


class HttpMethodsModule(BaseModule):
    key = "http_methods"
    name = "HTTP methods"
    category = Category.INFRASTRUCTURE
    subtitle = "Allowed verbs (PUT/DELETE/TRACE)"
    accepts = (InputType.DOMAIN, InputType.URL)
    needs_network = True
    description = (
        "Requests OPTIONS to list allowed HTTP methods and flags risky ones "
        "(PUT/DELETE/TRACE/CONNECT). Diagnostic only — never invokes them."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        url = v if v.startswith("http") else f"https://{v}"
        try:
            resp = await ctx.http.request("OPTIONS", url, follow_redirects=True,
                                          headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"OPTIONS failed: {exc}", source_url=url)

        allow = resp.headers.get("allow", "") or resp.headers.get("access-control-allow-methods", "")
        methods = [m.strip().upper() for m in allow.split(",") if m.strip()]
        risky = [m for m in methods if m in RISKY]

        findings = [
            {"label": "Allow header", "summary": allow or "(not advertised)"},
            {"label": "Methods", "values": methods or ["server didn't advertise any"]},
        ]
        if risky:
            findings.append({"label": "⚠ Risky methods enabled",
                             "summary": ", ".join(risky), "confidence": "medium"})
        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if risky else Confidence.INFO,
            source_url=url, raw={"allow": allow, "methods": methods},
            nodes=[GraphNode("domain", host_of(url))],
        )
