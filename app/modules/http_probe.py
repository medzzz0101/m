"""
modules/http_probe.py
=====================
Probe a domain/URL/IP over HTTP(S): is it live, what status, where does it
redirect, what server/tech do the response headers reveal, and what's the page
title. This is the "is this host actually serving something, and what" step.

We make a single GET (following redirects) and read the response — it's a normal
web request, not active exploitation. Security-relevant headers (HSTS/CSP/…) are
summarised so you can eyeball posture at a glance.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import host_of

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

# Header -> the technology/CDN it betrays.
TECH_HEADERS = {
    "server": "Server", "x-powered-by": "Powered-by", "via": "Via",
    "x-aspnet-version": "ASP.NET", "x-generator": "Generator",
}
SECURITY_HEADERS = [
    "strict-transport-security", "content-security-policy",
    "x-frame-options", "x-content-type-options", "referrer-policy",
    "permissions-policy",
]


class HttpProbeModule(BaseModule):
    key = "http_probe"
    name = "Live host probe"
    category = Category.INFRASTRUCTURE
    subtitle = "Status, redirects, headers, title"
    accepts = (InputType.DOMAIN, InputType.URL, InputType.IP)
    needs_network = True
    description = (
        "Fetches the host over HTTP(S): final status, full redirect chain, server "
        "and tech headers, page title, and a security-header summary."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        url = v if v.startswith(("http://", "https://")) else f"https://{v}"
        limiter = ctx.extra.get("rate_limiter")
        host = host_of(url)

        async def _get():
            return await ctx.http.get(
                url, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; osint-probe)"})
        try:
            if limiter is not None:
                async with limiter.slot(host):
                    resp = await _get()
            else:
                resp = await _get()
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Host not reachable over HTTPS: {exc}",
                               source_url=url)

        # Redirect chain.
        chain = [str(r.url) for r in resp.history] + [str(resp.url)]
        title_m = TITLE_RE.search(resp.text[:20000]) if resp.text else None
        title = (title_m.group(1).strip()[:120] if title_m else None)

        tech = {label: resp.headers[h] for h, label in TECH_HEADERS.items()
                if h in resp.headers}
        present_sec = [h for h in SECURITY_HEADERS if h in resp.headers]
        missing_sec = [h for h in SECURITY_HEADERS if h not in resp.headers]

        findings = [
            {"label": "Status", "summary": f"{resp.status_code} {resp.reason_phrase}"},
            {"label": "Final URL", "summary": str(resp.url)},
        ]
        if title:
            findings.append({"label": "Title", "summary": title})
        if len(chain) > 1:
            findings.append({"label": "Redirect chain", "values": chain})
        if tech:
            findings.append({"label": "Tech (headers)",
                             "values": [f"{k}: {v}" for k, v in tech.items()]})
        findings.append({
            "label": "Security headers",
            "summary": f"{len(present_sec)}/{len(SECURITY_HEADERS)} present",
            "values": ([f"✓ {h}" for h in present_sec] +
                       [f"✗ {h}" for h in missing_sec]),
            "confidence": "info",
        })

        nodes = [GraphNode("domain" if not v.replace(".", "").isdigit() else "ip",
                           host, props={"status": resp.status_code, "title": title})]
        edges: list[GraphEdge] = []
        # Tech nodes for correlation across hosts.
        for label, val in tech.items():
            t = f"{label}:{val}"
            nodes.append(GraphNode("tech", t, label=val))
            edges.append(GraphEdge(f"domain:{host}", f"tech:{t}", "runs_tech"))

        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if resp.status_code < 400 else Confidence.MEDIUM,
            source_url=str(resp.url),
            raw={"status": resp.status_code, "headers": dict(resp.headers),
                 "chain": chain, "title": title},
            nodes=nodes, edges=edges,
        )
