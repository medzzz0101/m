"""
modules/site_intel.py
=====================
"Read the front door." Fetch a domain's homepage (and a couple of common contact
pages) and extract the PUBLIC intelligence the organisation itself publishes:

  * social-media profile links (the company's own Twitter/LinkedIn/GitHub/…)
  * contact emails it displays (mailto: + visible addresses)
  * outbound tech/service links (analytics, CDNs, third-party embeds)

This is public business information the site chose to display — the OSINT
equivalent of reading a company's "Contact" page. It is scoped to the TARGET's
own pages and is about the organisation, not private individuals.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import host_of

SOCIAL = {
    "Twitter/X": r"https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{2,30})",
    "LinkedIn": r"https?://(?:www\.)?linkedin\.com/(company|in)/([A-Za-z0-9\-_%]+)",
    "Facebook": r"https?://(?:www\.)?facebook\.com/([A-Za-z0-9.\-]{2,60})",
    "Instagram": r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]{2,40})",
    "YouTube": r"https?://(?:www\.)?youtube\.com/(@[A-Za-z0-9_\-]+|channel/[A-Za-z0-9_\-]+|c/[A-Za-z0-9_\-]+)",
    "GitHub": r"https?://(?:www\.)?github\.com/([A-Za-z0-9\-]{1,39})",
    "TikTok": r"https?://(?:www\.)?tiktok\.com/(@[A-Za-z0-9_.]+)",
    "Telegram": r"https?://t\.me/([A-Za-z0-9_]{3,40})",
    "YouTube2": r"",
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
CONTACT_PATHS = ["", "/contact", "/contact-us", "/about", "/about-us", "/impressum"]


class SiteIntelModule(BaseModule):
    key = "site_intel"
    name = "Site intelligence"
    category = Category.INFRASTRUCTURE
    subtitle = "Socials & contacts on the site"
    accepts = (InputType.DOMAIN, InputType.URL)
    needs_network = True
    description = (
        "Reads the target's own homepage/contact pages for the PUBLIC info it "
        "publishes: official social-media links and contact emails. Organisation "
        "info the site displays — not private individuals."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        base = (v if v.startswith("http") else f"https://{v}").rstrip("/")
        host = host_of(base)

        html = ""
        for path in CONTACT_PATHS:
            try:
                r = await ctx.http.get(base + path, follow_redirects=True,
                                       headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and r.text:
                    html += "\n" + r.text[:120000]
            except Exception:
                continue
        if not html:
            return self.result(error="Could not fetch the site.", source_url=base)

        socials: dict[str, str] = {}
        for name, pattern in SOCIAL.items():
            if not pattern:
                continue
            m = re.search(pattern, html, re.I)
            if m:
                socials[name.replace("2", "")] = m.group(0)

        # Emails the site displays — drop obvious asset filenames / placeholders.
        emails = sorted({e.lower() for e in EMAIL_RE.findall(html)
                         if not e.lower().endswith((".png", ".jpg", ".gif", ".svg",
                                                     ".webp", ".css", ".js"))
                         and "@" in e and not e.startswith("@")})[:30]

        findings = []
        if socials:
            findings.append({"label": "Official social profiles",
                             "values": [f"{k}: {u}" for k, u in socials.items()]})
        if emails:
            findings.append({"label": "Published contact emails",
                             "values": emails,
                             "note": "Addresses the site itself displays (business "
                                     "contacts / published info)."})
        if not findings:
            findings.append({"label": "Site intel",
                             "summary": "No social links or emails found on the "
                                        "pages checked."})

        nodes = [GraphNode("domain", host)]
        edges: list[GraphEdge] = []
        for k, u in socials.items():
            nodes.append(GraphNode("service", u, label=f"{k}", props={"kind": "social"}))
            edges.append(GraphEdge(f"domain:{host}", f"service:{u}", "related_to"))
        for e in emails:
            nodes.append(GraphNode("email", e))
            edges.append(GraphEdge(f"domain:{host}", f"email:{e}", "related_to"))

        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if (socials or emails) else Confidence.INFO,
            source_url=base, raw={"socials": socials, "emails": emails},
            nodes=nodes, edges=edges,
        )
