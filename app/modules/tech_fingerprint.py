"""
modules/tech_fingerprint.py
===========================
"What is this site built with?" A lightweight Wappalyzer-style fingerprinter.
It fetches the page once and matches a curated signature set against the
response HEADERS, cookies, HTML, meta tags and script sources to name the web
server, CMS, frameworks, analytics, CDNs and languages in use.

Signatures are simple and transparent (regex / substring) so you can read and
extend them — the point is to learn how fingerprinting works, not to ship a
1000-rule black box.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import host_of

# Each signature: name -> {where: pattern}. `where` is header name, "cookie",
# "html", or "script". First match wins per technology.
SIGNATURES: dict[str, dict[str, str]] = {
    "WordPress": {"html": r"wp-content|wp-includes", "meta": r"WordPress"},
    "Drupal": {"header:x-generator": r"Drupal", "html": r"sites/default/files"},
    "Joomla": {"html": r"/media/jui/|Joomla!"},
    "Ghost": {"html": r"content=\"Ghost"},
    "Shopify": {"header:x-shopify-stage": r".", "html": r"cdn\.shopify\.com"},
    "Wix": {"html": r"static\.wixstatic\.com|X-Wix"},
    "Squarespace": {"html": r"static1\.squarespace\.com"},
    "React": {"html": r"data-reactroot|__REACT_DEVTOOLS", "script": r"react(\.min)?\.js"},
    "Vue.js": {"html": r"data-v-[0-9a-f]{8}", "script": r"vue(\.min)?\.js"},
    "Angular": {"html": r"ng-version|ng-app", "script": r"angular(\.min)?\.js"},
    "Next.js": {"html": r"/_next/|__NEXT_DATA__"},
    "Nuxt.js": {"html": r"__NUXT__|/_nuxt/"},
    "jQuery": {"script": r"jquery(-[\d.]+)?(\.min)?\.js"},
    "Bootstrap": {"html": r"bootstrap(\.min)?\.css", "script": r"bootstrap(\.min)?\.js"},
    "Tailwind CSS": {"html": r"tailwind"},
    "Cloudflare": {"header:server": r"cloudflare", "header:cf-ray": r"."},
    "Fastly": {"header:x-served-by": r"cache-.*", "header:fastly-.*": r"."},
    "Amazon CloudFront": {"header:x-amz-cf-id": r".", "header:via": r"CloudFront"},
    "Akamai": {"header:x-akamai-.*": r".", "header:server": r"AkamaiGHost"},
    "Nginx": {"header:server": r"nginx"},
    "Apache": {"header:server": r"Apache"},
    "Microsoft IIS": {"header:server": r"IIS|Microsoft-IIS"},
    "LiteSpeed": {"header:server": r"LiteSpeed"},
    "PHP": {"header:x-powered-by": r"PHP", "cookie": r"PHPSESSID"},
    "ASP.NET": {"header:x-powered-by": r"ASP\.NET", "header:x-aspnet-version": r".",
                "cookie": r"ASP\.NET_SessionId"},
    "Express": {"header:x-powered-by": r"Express"},
    "Ruby on Rails": {"cookie": r"_rails|_session_id", "header:x-powered-by": r"Phusion"},
    "Google Analytics": {"html": r"google-analytics\.com|gtag\(|GoogleAnalytics"},
    "Google Tag Manager": {"html": r"googletagmanager\.com"},
    "HSTS enabled": {"header:strict-transport-security": r"."},
    "Varnish": {"header:via": r"varnish", "header:x-varnish": r"."},
    "Cloudflare Turnstile": {"html": r"challenges\.cloudflare\.com"},
}


class TechFingerprintModule(BaseModule):
    key = "tech_fingerprint"
    name = "Tech fingerprint"
    category = Category.INFRASTRUCTURE
    subtitle = "CMS, frameworks, CDN, server"
    accepts = (InputType.DOMAIN, InputType.URL, InputType.IP)
    needs_network = True
    description = (
        "Wappalyzer-style fingerprinting from headers, cookies, HTML, meta and "
        "scripts: web server, CMS, JS frameworks, analytics and CDN."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        url = v if v.startswith(("http://", "https://")) else f"https://{v}"
        limiter = ctx.extra.get("rate_limiter")
        host = host_of(url)
        try:
            async def _g():
                return await ctx.http.get(url, follow_redirects=True,
                                          headers={"User-Agent": "Mozilla/5.0 (tech)"})
            if limiter is not None:
                async with limiter.slot(host):
                    resp = await _g()
            else:
                resp = await _g()
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Fetch failed: {exc}", source_url=url)

        headers = {k.lower(): v for k, v in resp.headers.items()}
        cookies = "; ".join(resp.headers.get_list("set-cookie"))
        html = resp.text[:60000] if resp.text else ""

        detected: list[str] = []
        for tech, sigs in SIGNATURES.items():
            if self._matches(sigs, headers, cookies, html):
                detected.append(tech)

        findings = [{
            "label": "Technologies",
            "summary": f"{len(detected)} detected",
            "values": detected or ["none matched our signature set"],
        }]
        # Always surface the raw Server header as ground truth.
        if "server" in headers:
            findings.append({"label": "Server header", "summary": headers["server"]})

        nodes = [GraphNode("domain", host)]
        edges: list[GraphEdge] = []
        for tech in detected:
            nodes.append(GraphNode("tech", tech, label=tech))
            edges.append(GraphEdge(f"domain:{host}", f"tech:{tech}", "runs_tech"))

        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if detected else Confidence.INFO,
            source_url=url, raw={"detected": detected, "server": headers.get("server")},
            nodes=nodes, edges=edges,
        )

    @staticmethod
    def _matches(sigs, headers, cookies, html) -> bool:
        for where, pattern in sigs.items():
            try:
                if where.startswith("header:"):
                    hkey = where.split(":", 1)[1]
                    # Support wildcard header names like "x-akamai-.*".
                    for hn, hv in headers.items():
                        if re.fullmatch(hkey, hn) and re.search(pattern, hv, re.I):
                            return True
                elif where == "cookie":
                    if re.search(pattern, cookies, re.I):
                        return True
                elif where in ("html", "meta", "script"):
                    if re.search(pattern, html, re.I):
                        return True
            except re.error:
                continue
        return False
