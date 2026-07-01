"""
modules/waf_cdn.py
==================
Detect the CDN / WAF (Web Application Firewall) fronting a site. Knowing a target
sits behind Cloudflare, Akamai, AWS, etc. tells you the real origin is hidden and
shapes how you interpret everything else (the IP you see is the edge, not the
server). We infer it from response headers, cookies and the CNAME chain — the
same tells `wafw00f`/`cdncheck` use.
"""

from __future__ import annotations

import asyncio

import dns.resolver

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import host_of

# provider -> header/cookie signals (lowercased substring match)
SIGNALS = {
    "Cloudflare": {"headers": ["cf-ray", "cf-cache-status"], "server": ["cloudflare"],
                   "cookie": ["__cfduid", "__cf_bm"], "cname": ["cloudflare"]},
    "Akamai": {"headers": ["x-akamai-transformed", "akamai-grn"],
               "server": ["akamaighost"], "cname": ["akamai", "edgekey", "edgesuite"]},
    "Amazon CloudFront": {"headers": ["x-amz-cf-id", "x-amz-cf-pop"],
                          "server": ["cloudfront"], "cname": ["cloudfront.net"]},
    "Fastly": {"headers": ["x-served-by", "x-fastly-request-id"],
               "server": ["fastly"], "cname": ["fastly"]},
    "Sucuri": {"headers": ["x-sucuri-id", "x-sucuri-cache"], "server": ["sucuri"]},
    "Imperva/Incapsula": {"headers": ["x-iinfo", "x-cdn"], "cookie": ["incap_ses", "visid_incap"]},
    "Google Cloud": {"server": ["gws", "gse"], "cname": ["googlehosted", "ghs.google"]},
    "Microsoft Azure": {"cname": ["azureedge", "azurefd", "trafficmanager"]},
    "StackPath": {"headers": ["x-hw"], "cname": ["stackpathdns", "stackpathcdn"]},
    "Vercel": {"headers": ["x-vercel-id"], "server": ["vercel"], "cname": ["vercel"]},
    "Netlify": {"headers": ["x-nf-request-id"], "server": ["netlify"], "cname": ["netlify"]},
    "Cloudflare (Turnstile/WAF)": {"headers": ["cf-mitigated"]},
}


def _cname_chain(host: str) -> list[str]:
    out = []
    try:
        r = dns.resolver.Resolver(); r.lifetime = 4.0
        cur = host
        for _ in range(6):
            ans = r.resolve(cur, "CNAME")
            target = ans[0].target.to_text().rstrip(".")
            out.append(target)
            cur = target
    except Exception:
        pass
    return out


class WafCdnModule(BaseModule):
    key = "waf_cdn_detect"
    name = "WAF / CDN detect"
    category = Category.INFRASTRUCTURE
    subtitle = "Edge provider fingerprint"
    accepts = (InputType.DOMAIN, InputType.URL)
    needs_network = True
    description = (
        "Identifies the CDN/WAF in front of a site (Cloudflare, Akamai, Fastly, "
        "CloudFront, Sucuri, Imperva…) from headers, cookies and the CNAME chain."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        host = host_of(v if v.startswith("http") else f"https://{v}")
        url = v if v.startswith("http") else f"https://{v}"

        try:
            resp = await ctx.http.get(url, follow_redirects=True,
                                      headers={"User-Agent": "Mozilla/5.0"})
            headers = {k.lower(): v.lower() for k, v in resp.headers.items()}
            cookies = "; ".join(resp.headers.get_list("set-cookie")).lower()
        except Exception:
            headers, cookies = {}, ""

        loop = asyncio.get_running_loop()
        cnames = [c.lower() for c in await loop.run_in_executor(None, _cname_chain, host)]

        hits: dict[str, list[str]] = {}
        for provider, sig in SIGNALS.items():
            why = []
            for h in sig.get("headers", []):
                if h in headers:
                    why.append(f"header {h}")
            for s in sig.get("server", []):
                if s in headers.get("server", ""):
                    why.append(f"server={headers['server']}")
            for c in sig.get("cookie", []):
                if c in cookies:
                    why.append(f"cookie {c}")
            for cn in sig.get("cname", []):
                if any(cn in x for x in cnames):
                    why.append(f"CNAME→{cn}")
            if why:
                hits[provider] = why

        findings = [{
            "label": "Edge provider(s)",
            "summary": ", ".join(hits) if hits else "none detected (likely direct-origin)",
            "values": [f"{p}: {', '.join(w)}" for p, w in hits.items()] or None,
        }]
        if cnames:
            findings.append({"label": "CNAME chain", "values": cnames})

        nodes = [GraphNode("domain", host)]
        edges: list[GraphEdge] = []
        for p in hits:
            nodes.append(GraphNode("org", p, label=p, props={"role": "cdn/waf"}))
            edges.append(GraphEdge(f"domain:{host}", f"org:{p}", "hosted_on"))

        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if hits else Confidence.INFO,
            source_url=url, raw={"providers": hits, "cnames": cnames},
            nodes=nodes, edges=edges,
        )
