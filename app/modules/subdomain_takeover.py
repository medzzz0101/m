"""
modules/subdomain_takeover.py
=============================
Detect DANGLING subdomains vulnerable to takeover. When a subdomain has a CNAME
pointing at a third-party service (GitHub Pages, Heroku, S3, Azure, Shopify…) but
that resource was deleted/never-claimed, an attacker can register it and serve
content from YOUR subdomain. We look for the tell-tale "not found" fingerprints
each service returns for an unclaimed host.

We pull candidate subdomains from CT (certspotter), resolve their CNAMEs and
fetch them, matching known fingerprints. Passive checks (DNS + a normal GET);
we report the risk, we do not perform any takeover.
"""

from __future__ import annotations

import asyncio

import dns.resolver

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json, host_of

# service label -> (cname substrings, body fingerprint of an UNCLAIMED resource)
FINGERPRINTS = [
    ("GitHub Pages", ["github.io"], "There isn't a GitHub Pages site here"),
    ("Heroku", ["herokuapp.com", "herokudns"], "No such app"),
    ("AWS S3", ["s3.amazonaws.com", "s3-website"], "NoSuchBucket"),
    ("Azure", ["azurewebsites.net", "cloudapp.net", "trafficmanager.net"], "404 Web Site not found"),
    ("Shopify", ["myshopify.com"], "Sorry, this shop is currently unavailable"),
    ("Fastly", ["fastly.net"], "Fastly error: unknown domain"),
    ("Bitbucket", ["bitbucket.io"], "Repository not found"),
    ("Surge.sh", ["surge.sh"], "project not found"),
    ("Tumblr", ["tumblr.com"], "Whatever you were looking for doesn't currently exist"),
    ("Zendesk", ["zendesk.com"], "Help Center Closed"),
    ("Unbounce", ["unbounce.com"], "The requested URL was not found"),
    ("Readthedocs", ["readthedocs.io"], "unknown to Read the Docs"),
    ("Pantheon", ["pantheonsite.io"], "The gods are wise"),
    ("Netlify", ["netlify.app", "netlify.com"], "Not Found - Request ID"),
]


def _cname(host: str) -> str | None:
    try:
        r = dns.resolver.Resolver(); r.lifetime = 4.0
        ans = r.resolve(host, "CNAME")
        return ans[0].target.to_text().rstrip(".").lower()
    except Exception:
        return None


class SubdomainTakeoverModule(BaseModule):
    key = "subdomain_takeover"
    name = "Subdomain takeover"
    category = Category.INFRASTRUCTURE
    subtitle = "Dangling CNAME risk"
    accepts = (InputType.DOMAIN,)
    needs_network = True
    description = (
        "Checks subdomains for dangling CNAMEs pointing at unclaimed third-party "
        "services (GitHub Pages/Heroku/S3/Azure/Shopify…) — a takeover risk. "
        "Passive: DNS + a normal GET, no takeover performed."
    )

    async def _subdomains(self, domain: str, ctx) -> list[str]:
        try:
            data = await fetch_json(
                ctx, f"https://api.certspotter.com/v1/issuances?domain={domain}"
                     f"&include_subdomains=true&expand=dns_names",
                ttl=21600, namespace="certspotter")
        except Exception:
            return []
        names = set()
        for iss in data or []:
            for n in iss.get("dns_names", []):
                n = n.lower().lstrip("*.")
                if n.endswith(domain) and n != domain:
                    names.add(n)
        return sorted(names)[:40]   # bound the work

    async def _check(self, sub: str, ctx) -> dict | None:
        loop = asyncio.get_running_loop()
        cname = await loop.run_in_executor(None, _cname, sub)
        if not cname:
            return None
        service = next((f for f in FINGERPRINTS
                        if any(s in cname for s in f[1])), None)
        if not service:
            return None
        # It points at a known service — is that resource unclaimed?
        try:
            resp = await ctx.http.get(f"https://{sub}", follow_redirects=True,
                                      headers={"User-Agent": "Mozilla/5.0"})
            body = resp.text[:4000]
        except Exception:
            body = ""
        vulnerable = service[2].lower() in body.lower()
        return {"sub": sub, "cname": cname, "service": service[0],
                "vulnerable": vulnerable}

    async def run(self, value: str, ctx: RunContext):
        domain = value.lower().strip().lstrip("*.")
        subs = await self._subdomains(domain, ctx)
        if not subs:
            return self.result(
                findings=[{"label": "Subdomains", "summary": "none found in CT to check."}],
                confidence=Confidence.INFO)

        results = [r for r in await asyncio.gather(
            *(self._check(s, ctx) for s in subs)) if r]
        vulns = [r for r in results if r["vulnerable"]]
        pointed = [r for r in results if not r["vulnerable"]]

        findings = [{
            "label": "Checked",
            "summary": f"{len(subs)} subdomains · {len(results)} point at 3rd-party services",
            "confidence": "info",
        }]
        if vulns:
            findings.append({
                "label": "⚠ Takeover-vulnerable",
                "summary": f"{len(vulns)} dangling subdomain(s)!",
                "values": [f"{r['sub']} → {r['service']} ({r['cname']})" for r in vulns],
                "confidence": "high"})
        if pointed:
            findings.append({
                "label": "Third-party (claimed)",
                "values": [f"{r['sub']} → {r['service']}" for r in pointed[:20]],
                "confidence": "info"})
        if not results:
            findings.append({"label": "Result",
                             "summary": "No subdomains point at takeover-prone services."})

        nodes = [GraphNode("domain", domain)]
        edges: list[GraphEdge] = []
        for r in vulns:
            nodes.append(GraphNode("subdomain", r["sub"],
                                   props={"takeover": True, "service": r["service"]}))
            edges.append(GraphEdge(f"domain:{domain}", f"subdomain:{r['sub']}", "exposes",
                                   props={"risk": "takeover"}))
        return self.result(
            confidence=Confidence.HIGH if vulns else Confidence.INFO,
            findings=findings, raw={"results": results}, nodes=nodes, edges=edges,
        )
