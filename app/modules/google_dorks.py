"""
modules/google_dorks.py
=======================
A Google-dork GENERATOR. Offline, no network: given a domain it builds a set of
ready-to-click advanced-search queries ("dorks") that surface exposed documents,
login portals, config files, directory listings and more on public search
engines. This is the classic first move in an OSINT engagement — we just turn the
target into the queries so you can run them with one tap.

Every query is a normal public search; nothing here fetches or bypasses anything.
"""

from __future__ import annotations

from urllib.parse import quote

from app.core.base import (
    BaseModule, Category, Confidence, InputType, RunContext,
)

# (label, google query template).  {d} = domain.
DORKS = [
    ("Indexed subdomains", "site:*.{d} -www"),
    ("Exposed documents", "site:{d} (ext:pdf OR ext:doc OR ext:docx OR ext:xls OR ext:xlsx)"),
    ("Config & env files", "site:{d} (ext:env OR ext:cfg OR ext:conf OR ext:ini OR ext:yml)"),
    ("Backups & archives", "site:{d} (ext:bak OR ext:old OR ext:sql OR ext:zip OR ext:tar)"),
    ("Login / admin portals", "site:{d} (inurl:login OR inurl:admin OR inurl:portal)"),
    ("Directory listings", 'site:{d} intitle:"index of"'),
    ("Open redirects / params", "site:{d} (inurl:redirect OR inurl:url= OR inurl:next=)"),
    ("Error messages / stack traces", 'site:{d} ("sql syntax near" OR "stack trace" OR "fatal error")'),
    ("API keys / secrets in pages", 'site:{d} (intext:"api_key" OR intext:"secret" OR intext:"password")'),
    ("Git / SVN exposure", "site:{d} (inurl:.git OR inurl:.svn)"),
    ("Cloud storage links", '"{d}" (site:s3.amazonaws.com OR site:storage.googleapis.com OR site:blob.core.windows.net)'),
    ("Pastes & code mentions", '"{d}" (site:pastebin.com OR site:github.com OR site:gitlab.com)'),
    ("Documents on 3rd-party hosts", '"{d}" (site:scribd.com OR site:slideshare.net OR site:docdroid.net)'),
    ("Employees / profiles (org context)", '"{d}" site:linkedin.com/in'),
]


class GoogleDorksModule(BaseModule):
    key = "google_dorks"
    name = "Dork generator"
    category = Category.INTEL
    subtitle = "Ready-to-run search queries"
    accepts = (InputType.DOMAIN, InputType.TEXT)
    needs_network = False
    description = (
        "Generates advanced search-engine queries (Google dorks) for a domain: "
        "exposed docs, config/backups, login portals, directory listings, secrets "
        "and more. Offline — just builds the clickable queries."
    )

    async def run(self, value: str, ctx: RunContext):
        domain = value.strip().lower().lstrip("*. ")
        if "." not in domain:
            return self.result(error="Provide a domain (e.g. example.com).")

        findings = [{
            "label": "How to use",
            "summary": "Each item is a clickable Google search. Also try them on "
                       "Bing/DuckDuckGo — engines index different things.",
            "confidence": "info",
        }]
        for label, tmpl in DORKS:
            q = tmpl.format(d=domain)
            link = f"https://www.google.com/search?q={quote(q)}"
            findings.append({"label": label, "summary": q, "values": [link]})

        return self.result(
            findings=findings, confidence=Confidence.INFO,
            raw={"domain": domain, "count": len(DORKS)},
        )
