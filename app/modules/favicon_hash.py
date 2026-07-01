"""
modules/favicon_hash.py
=======================
Compute the MurmurHash3 of a site's favicon, the same way Shodan does. Why?
Because many organisations serve the SAME favicon across all their (sometimes
otherwise-unlinked) infrastructure. The favicon hash is therefore a powerful
correlation key: search it on Shodan and you find sibling hosts sharing the icon.

Algorithm (the Shodan convention): base64-encode the raw bytes WITH newline
wrapping (like Python's base64.encodebytes), then mmh3.hash() that text.
"""

from __future__ import annotations

import base64

import mmh3

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import host_of


class FaviconHashModule(BaseModule):
    key = "favicon_hash"
    name = "Favicon hash"
    category = Category.INFRASTRUCTURE
    subtitle = "mmh3 — pivot shared infra"
    accepts = (InputType.DOMAIN, InputType.URL, InputType.IP)
    needs_network = True
    description = (
        "Hashes the site favicon with MurmurHash3 (Shodan convention). Shared "
        "favicon hashes reveal related infrastructure across hosts."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        base = v if v.startswith(("http://", "https://")) else f"https://{v}"
        url = base.rstrip("/") + "/favicon.ico"
        limiter = ctx.extra.get("rate_limiter")
        host = host_of(base)

        async def _get():
            return await ctx.http.get(url, follow_redirects=True,
                                      headers={"User-Agent": "Mozilla/5.0"})
        try:
            if limiter is not None:
                async with limiter.slot(host):
                    resp = await _get()
            else:
                resp = await _get()
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Favicon fetch failed: {exc}", source_url=url)

        if resp.status_code != 200 or not resp.content:
            return self.result(
                findings=[{"label": "Favicon", "summary": f"none served "
                           f"(HTTP {resp.status_code})"}],
                confidence=Confidence.INFO, source_url=url)

        # Shodan-style hash: base64(encodebytes) of the raw bytes, then mmh3.
        b64 = base64.encodebytes(resp.content)
        fhash = mmh3.hash(b64)

        shodan_q = f"https://www.shodan.io/search?query=http.favicon.hash%3A{fhash}"
        findings = [
            {"label": "Favicon hash (mmh3)", "summary": str(fhash)},
            {"label": "Size", "summary": f"{len(resp.content)} bytes"},
            {"label": "Pivot", "summary": "Find hosts with the same favicon",
             "values": [shodan_q]},
        ]
        nodes = [GraphNode("domain", host),
                 GraphNode("favicon", str(fhash), label=f"favicon {fhash}")]
        edges = [GraphEdge(f"domain:{host}", f"favicon:{fhash}", "shares_favicon")]
        return self.result(
            findings=findings, confidence=Confidence.MEDIUM,
            source_url=shodan_q, raw={"hash": fhash, "bytes": len(resp.content)},
            nodes=nodes, edges=edges,
        )
