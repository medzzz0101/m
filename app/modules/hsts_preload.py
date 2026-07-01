"""
modules/hsts_preload.py
=======================
Check whether a domain is on the HSTS preload list — the list baked into browsers
that forces HTTPS for a domain on the very first request (before any header is
seen). Being preloaded is a strong security posture signal; not being preloaded
(especially with no HSTS header) means first-visit downgrade attacks are possible.

Uses hstspreload.org's public status API (no key).
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json, host_of


class HstsPreloadModule(BaseModule):
    key = "hsts_preload"
    name = "HSTS preload"
    category = Category.INFRASTRUCTURE
    subtitle = "Browser HTTPS-preload status"
    accepts = (InputType.DOMAIN, InputType.URL)
    needs_network = True
    description = (
        "Checks whether a domain is on the browser HSTS preload list (forces HTTPS "
        "from first request). A strong transport-security signal."
    )

    async def run(self, value: str, ctx: RunContext):
        host = host_of(value if value.startswith("http") else f"https://{value}")
        url = f"https://hstspreload.org/api/v2/status?domain={host}"
        try:
            data = await fetch_json(ctx, url, ttl=86400, namespace="hsts")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"HSTS preload check failed: {exc}", source_url=url)

        status = data.get("status", "unknown")
        preloaded = status == "preloaded"
        findings = [
            {"label": "Preload status", "summary": status,
             "confidence": "high" if preloaded else "info"},
            {"label": "Preloaded",
             "summary": "yes — HTTPS forced from first request" if preloaded
             else "no — first-visit HTTP downgrade is possible",
             "confidence": "info" if preloaded else "medium"},
        ]
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if preloaded else Confidence.INFO,
            source_url=f"https://hstspreload.org/?domain={host}",
            raw=data, nodes=[GraphNode("domain", host, props={"hsts_preload": preloaded})],
        )
