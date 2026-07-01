"""
modules/wellknown.py
====================
Fetch and read a site's "well-known" files — the small, standard, PUBLIC files
that quietly reveal a lot:

  * robots.txt        — disallowed paths (often admin/staging areas), sitemaps
  * sitemap.xml       — the site's own map of URLs
  * /.well-known/security.txt — security contact + policy (RFC 9116)
  * humans.txt, ads.txt — team/vendor hints

These are meant to be read; we just collect and summarise them so you don't have
to open five tabs.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, InputType, RunContext, GraphNode,
)
from ._common import host_of

FILES = ["robots.txt", "sitemap.xml", ".well-known/security.txt",
         "humans.txt", "ads.txt"]


class WellKnownModule(BaseModule):
    key = "wellknown"
    name = "Well-known files"
    category = Category.INFRASTRUCTURE
    subtitle = "robots, sitemap, security.txt"
    accepts = (InputType.DOMAIN, InputType.URL)
    needs_network = True
    description = (
        "Collects robots.txt (disallowed/admin paths + sitemaps), sitemap.xml, "
        "security.txt (RFC 9116 contact), humans.txt and ads.txt."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        base = (v if v.startswith("http") else f"https://{v}").rstrip("/")
        host = host_of(base)
        findings: list[dict] = []
        raw: dict = {}

        for fname in FILES:
            url = f"{base}/{fname}"
            try:
                resp = await ctx.http.get(url, headers={"User-Agent": "Mozilla/5.0"},
                                          follow_redirects=True)
            except Exception:
                continue
            if resp.status_code != 200 or not resp.text.strip():
                continue
            text = resp.text
            raw[fname] = text[:4000]

            if fname == "robots.txt":
                disallows = re.findall(r"(?im)^\s*Disallow:\s*(\S+)", text)
                sitemaps = re.findall(r"(?im)^\s*Sitemap:\s*(\S+)", text)
                findings.append({
                    "label": "robots.txt",
                    "summary": f"{len(disallows)} Disallow rule(s)",
                    "values": (sorted(set(disallows))[:40]) or ["(present, no rules)"],
                })
                if sitemaps:
                    findings.append({"label": "Sitemaps (declared)", "values": sitemaps[:10]})
            elif fname == ".well-known/security.txt":
                contacts = re.findall(r"(?im)^\s*Contact:\s*(\S+)", text)
                findings.append({"label": "security.txt",
                                 "summary": "present (RFC 9116)",
                                 "values": contacts or ["(present)"]})
            elif fname == "sitemap.xml":
                locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", text)
                findings.append({"label": "sitemap.xml",
                                 "summary": f"{len(locs)} URL(s) listed",
                                 "values": locs[:25]})
            else:
                findings.append({"label": fname, "summary": "present"})

        if not findings:
            findings.append({"label": "Well-known files",
                             "summary": "none of the standard files were served."})

        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if raw else Confidence.INFO,
            source_url=f"{base}/robots.txt", raw=raw,
            nodes=[GraphNode("domain", host)],
        )
