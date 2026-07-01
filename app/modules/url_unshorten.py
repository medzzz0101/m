"""
modules/url_unshorten.py
========================
Expand a shortened / redirecting URL to reveal its final destination and the full
redirect chain — without opening it in your own browser. Short links (bit.ly,
t.co, tinyurl, lnkd.in…) hide where they really go; this follows the hops and
reports every stop, so you can see the true target before trusting it.

Follows HTTP redirects only; it does not execute page content.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import host_of


class UrlUnshortenModule(BaseModule):
    key = "url_unshorten"
    name = "URL unshortener"
    category = Category.INTEL
    subtitle = "Reveal a short link's target"
    accepts = (InputType.URL,)
    needs_network = True
    description = (
        "Expands a shortened/redirecting URL to its final destination and shows "
        "the full redirect chain. Follows redirects only — no page execution."
    )

    async def run(self, value: str, ctx: RunContext):
        url = value.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            resp = await ctx.http.get(url, follow_redirects=True,
                                      headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Could not follow the URL: {exc}", source_url=url)

        chain = [str(r.url) for r in resp.history] + [str(resp.url)]
        final = str(resp.url)
        crossed = host_of(url) != host_of(final)

        findings = [
            {"label": "Final destination", "summary": final,
             "confidence": "high"},
            {"label": "Final host", "summary": host_of(final)},
            {"label": "Redirects", "summary": f"{len(resp.history)} hop(s)",
             "values": chain if len(chain) > 1 else None},
            {"label": "Status", "summary": f"{resp.status_code}"},
        ]
        if crossed:
            findings.append({"label": "Note",
                             "summary": "The short link points to a DIFFERENT host "
                                        "than it appears — verify before trusting.",
                             "confidence": "medium"})

        nodes = [GraphNode("url", url, label=host_of(url)),
                 GraphNode("domain", host_of(final))]
        edges = [GraphEdge(f"url:{url}", f"domain:{host_of(final)}", "redirects_to")]
        return self.result(
            findings=findings, confidence=Confidence.HIGH, source_url=final,
            raw={"chain": chain, "final": final}, nodes=nodes, edges=edges,
        )
