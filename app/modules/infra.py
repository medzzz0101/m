"""infra.py — infrastructure & attack-surface OSINT (all public sources).

Domains, IPs, DNS, TLS certificates, hosting/ASN, subdomains via Certificate
Transparency, HTTP fingerprinting, and threat-intel context. Everything uses
official/public APIs or standard protocols; nothing here exploits a target.
"""
from __future__ import annotations

import asyncio
import re
import socket
import ssl

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client


def _host_of(target: str) -> str:
    """Strip scheme/path so modules get a bare hostname."""
    t = target.strip()
    t = re.sub(r"^https?://", "", t, flags=re.I)
    return t.split("/")[0].split(":")[0]


class DnsRecords(BaseModule):
    id = "dns_records"
    name = "DNS records"
    description = "A/AAAA/MX/NS/TXT/CNAME/SOA resolution for a domain."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.URL)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import dns.asyncresolver
        res = self.result()
        host = _host_of(ctx.target)
        dnode = res.node("domain", host, label=host)
        resolver = dns.asyncresolver.Resolver()
        resolver.lifetime = 6.0
        for rtype in ("A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA"):
            try:
                ans = await resolver.resolve(host, rtype)
                for rr in ans:
                    val = rr.to_text().strip('"')
                    conf = Confidence.CONFIRMED
                    pivot = val if rtype in ("A", "AAAA") else None
                    res.add(rtype, val, conf, pivot=pivot)
                    if rtype in ("A", "AAAA"):
                        ipn = res.node("ip", val, label=val); res.edge(dnode.id, ipn.id, "resolves_to")
            except Exception:
                continue
        res.summary = f"{len(res.findings)} DNS records for {host}"
        return res


class WhoisRdap(BaseModule):
    id = "whois_rdap"
    name = "WHOIS / RDAP"
    description = "Registration data for a domain or IP via the official RDAP protocol."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.IP, InputType.URL)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        is_ip = ctx.input_type == InputType.IP
        url = f"https://rdap.org/{'ip' if is_ip else 'domain'}/{host}"
        try:
            r = await get_client().get(url)
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = f"No RDAP data (HTTP {r.status_code})"; return res
        d = r.json()
        res.node("domain" if not is_ip else "ip", host, label=host)
        if d.get("handle"): res.add("Handle", d["handle"], Confidence.CONFIRMED)
        for ev in d.get("events", []):
            res.add(ev.get("eventAction", "event").title(),
                    (ev.get("eventDate") or "")[:10], Confidence.CONFIRMED)
        for ent in d.get("entities", [])[:4]:
            roles = ",".join(ent.get("roles", []))
            res.add(f"Entity ({roles})", ent.get("handle", "—"), Confidence.INFO)
        ns = [n.get("ldhName") for n in d.get("nameservers", []) if n.get("ldhName")]
        if ns: res.add("Nameservers", ", ".join(ns), Confidence.CONFIRMED)
        res.summary = f"RDAP record for {host}"
        return res


class IpGeo(BaseModule):
    id = "ip_geo"
    name = "IP geolocation & host"
    description = "Approximate geo, ISP, ASN and org for an IP (public geo-IP)."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.IP, InputType.DOMAIN, InputType.URL)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        # Resolve domain to IP first if needed.
        ip = host
        if ctx.input_type != InputType.IP:
            try:
                ip = socket.gethostbyname(host)
            except Exception:
                pass
        # ipwho.is: free, HTTPS, no key (our proxy only allows HTTPS CONNECT).
        try:
            r = await get_client().get(f"https://ipwho.is/{ip}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        d = r.json()
        if not d.get("success"):
            res.summary = "No geolocation for this IP"; return res
        conn = d.get("connection", {})
        res.node("ip", d["ip"], label=d["ip"])
        res.add("IP", d["ip"], Confidence.CONFIRMED)
        loc = ", ".join(x for x in [d.get("city"), d.get("region"), d.get("country")] if x)
        res.add("Location (approx)", loc, Confidence.LIKELY)
        res.add("ISP", conn.get("isp", "—"), Confidence.LIKELY)
        res.add("Org", conn.get("org", "—"), Confidence.INFO)
        if conn.get("asn"): res.add("ASN", f"AS{conn['asn']}", Confidence.CONFIRMED)
        res.add("Timezone", (d.get("timezone") or {}).get("id", "—"), Confidence.INFO)
        if d.get("latitude") is not None:
            res.extra["map"] = {"lat": d["latitude"], "lon": d["longitude"],
                                "label": f"{loc} · {d['ip']}"}
        res.summary = f"{d['ip']} — {loc}"
        return res


class TlsCertificate(BaseModule):
    id = "tls_certificate"
    name = "TLS certificate"
    description = "Live certificate subject, issuer, SANs and validity for a host:443."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.URL, InputType.IP)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        try:
            der = await asyncio.get_event_loop().run_in_executor(None, self._fetch, host)
        except Exception as e:
            res.ok = False; res.error = f"TLS handshake failed: {e}"; return res
        if not der:
            res.summary = "No certificate retrieved"; return res
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        cert = x509.load_der_x509_certificate(der, default_backend())
        res.node("domain", host, label=host)
        res.add("Subject", cert.subject.rfc4514_string(), Confidence.CONFIRMED)
        res.add("Issuer", cert.issuer.rfc4514_string(), Confidence.CONFIRMED)
        res.add("Valid from", cert.not_valid_before_utc.strftime("%Y-%m-%d"), Confidence.CONFIRMED)
        res.add("Valid to", cert.not_valid_after_utc.strftime("%Y-%m-%d"), Confidence.CONFIRMED)
        try:
            sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            names = sans.value.get_values_for_type(x509.DNSName)
            for n in names[:25]:
                res.add("SAN", n, Confidence.LIKELY, pivot=n if n != host else None)
            res.extra["san_count"] = len(names)
        except Exception:
            pass
        res.summary = f"Cert for {host}, {res.extra.get('san_count',0)} SANs"
        return res

    @staticmethod
    def _fetch(host: str) -> bytes | None:
        # Direct TLS to :443 is allowed for connect in many envs; wrap defensively.
        ctxs = ssl.create_default_context()
        ctxs.check_hostname = False
        ctxs.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, 443), timeout=8) as sock:
            with ctxs.wrap_socket(sock, server_hostname=host) as ss:
                return ss.getpeercert(binary_form=True)


class SubdomainsCT(BaseModule):
    id = "subdomains_ct"
    name = "Subdomains (Cert Transparency)"
    description = "Enumerates subdomains from public Certificate Transparency logs."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.URL)
    tier = "premium"
    timeout = 20.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        subs: set[str] = set()
        try:
            r = await get_client().get(f"https://crt.sh/?q=%25.{host}&output=json")
            if r.status_code == 200:
                for row in r.json():
                    for nm in str(row.get("name_value", "")).split("\n"):
                        nm = nm.strip().lstrip("*.").lower()
                        if nm.endswith(host):
                            subs.add(nm)
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        dnode = res.node("domain", host, label=host)
        for s in sorted(subs)[:80]:
            res.add("subdomain", s, Confidence.LIKELY, pivot=s, link=f"https://{s}")
            sn = res.node("subdomain", s, label=s); res.edge(dnode.id, sn.id, "subdomain_of")
        res.summary = f"{len(subs)} unique subdomains from CT logs"
        res.extra["count"] = len(subs)
        return res


class HttpProbe(BaseModule):
    id = "http_probe"
    name = "HTTP fingerprint"
    description = "Status, server, redirect chain, and key response headers for a URL/host."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.URL, InputType.DOMAIN, InputType.IP)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        url = ctx.target if ctx.target.startswith("http") else f"https://{host}"
        try:
            r = await get_client().get(url)
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        res.node("domain", host, label=host)
        res.add("Final URL", str(r.url), Confidence.CONFIRMED, link=str(r.url))
        res.add("Status", r.status_code, Confidence.CONFIRMED)
        if len(r.history):
            res.add("Redirects", " → ".join(str(h.status_code) for h in r.history) + f" → {r.status_code}",
                    Confidence.INFO)
        for hk in ("server", "x-powered-by", "content-type", "via", "cf-ray",
                   "strict-transport-security", "content-security-policy"):
            if hk in r.headers:
                res.add(hk, r.headers[hk][:180], Confidence.INFO)
        res.summary = f"HTTP {r.status_code} · {r.headers.get('server','?')}"
        return res


class SecurityHeaders(BaseModule):
    id = "security_headers"
    name = "Security headers grade"
    description = "Checks for HSTS, CSP, X-Frame-Options and friends; grades the result."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.URL, InputType.DOMAIN)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        url = ctx.target if ctx.target.startswith("http") else f"https://{host}"
        try:
            r = await get_client().get(url)
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        wanted = {
            "strict-transport-security": "HSTS",
            "content-security-policy": "CSP",
            "x-frame-options": "X-Frame-Options",
            "x-content-type-options": "X-Content-Type-Options",
            "referrer-policy": "Referrer-Policy",
            "permissions-policy": "Permissions-Policy",
        }
        present = 0
        for hk, label in wanted.items():
            if hk in r.headers:
                present += 1
                res.add(label, "present", Confidence.CONFIRMED)
            else:
                res.add(label, "MISSING", Confidence.POSSIBLE)
        grade = ["F", "E", "D", "C", "B", "A", "A+"][present]
        res.add("Grade", grade, Confidence.CONFIRMED if present >= 4 else Confidence.POSSIBLE)
        res.summary = f"Security headers: {present}/6 present (grade {grade})"
        return res


class FaviconHash(BaseModule):
    id = "favicon_hash"
    name = "Favicon hash (mmh3)"
    description = "Computes the Shodan-style mmh3 favicon hash to correlate related hosts."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.URL, InputType.DOMAIN)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import base64, mmh3
        res = self.result()
        host = _host_of(ctx.target)
        url = ctx.target if ctx.target.startswith("http") else f"https://{host}"
        try:
            r = await get_client().get(url.rstrip("/") + "/favicon.ico")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200 or not r.content:
            res.summary = "No favicon found"; return res
        b64 = base64.encodebytes(r.content)
        h = mmh3.hash(b64)
        res.node("domain", host, label=host)
        res.add("Favicon mmh3", str(h), Confidence.CONFIRMED, pivot=str(h))
        res.add("Shodan pivot", f'http.favicon.hash:{h}', Confidence.INFO,
                link=f"https://www.shodan.io/search?query=http.favicon.hash%3A{h}")
        res.summary = f"Favicon hash {h}"
        return res


class ShodanInternetDB(BaseModule):
    id = "shodan_internetdb"
    name = "Shodan InternetDB"
    description = "Free Shodan InternetDB: open ports, hostnames, tags, CVEs for an IP."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.IP, InputType.DOMAIN)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        ip = host
        if ctx.input_type != InputType.IP:
            try: ip = socket.gethostbyname(host)
            except Exception: pass
        try:
            r = await get_client().get(f"https://internetdb.shodan.io/{ip}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "No InternetDB record"; return res
        d = r.json()
        res.node("ip", ip, label=ip)
        if d.get("ports"): res.add("Open ports", ", ".join(map(str, d["ports"])), Confidence.CONFIRMED)
        for hn in d.get("hostnames", [])[:10]:
            res.add("Hostname", hn, Confidence.LIKELY, pivot=hn)
        if d.get("tags"): res.add("Tags", ", ".join(d["tags"]), Confidence.INFO)
        for c in d.get("vulns", [])[:15]:
            res.add("CVE", c, Confidence.POSSIBLE,
                    link=f"https://nvd.nist.gov/vuln/detail/{c}")
        res.summary = f"{ip}: {len(d.get('ports',[]))} ports, {len(d.get('vulns',[]))} CVEs"
        return res


class GreyNoise(BaseModule):
    id = "greynoise"
    name = "GreyNoise context"
    description = "Community GreyNoise: is this IP a known internet scanner / noise source?"
    category = Category.INFRASTRUCTURE
    inputs = (InputType.IP,)
    tier = "elite"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        ip = _host_of(ctx.target)
        try:
            r = await get_client().get(f"https://api.greynoise.io/v3/community/{ip}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "No GreyNoise community data"; return res
        d = r.json()
        res.node("ip", ip, label=ip)
        res.add("Classification", d.get("classification", "unknown"),
                Confidence.LIKELY if d.get("classification") == "benign" else Confidence.POSSIBLE)
        res.add("Noise", d.get("noise", "—"), Confidence.INFO)
        res.add("RIOT", d.get("riot", "—"), Confidence.INFO)
        if d.get("name"): res.add("Actor/Name", d["name"], Confidence.INFO)
        res.summary = f"GreyNoise: {d.get('classification','unknown')}"
        return res


class Wayback(BaseModule):
    id = "wayback"
    name = "Wayback history"
    description = "First and most recent Internet Archive snapshots of a URL/domain."
    category = Category.INTEL
    inputs = (InputType.URL, InputType.DOMAIN)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        try:
            r = await get_client().get(
                "https://web.archive.org/cdx/search/cdx",
                params={"url": host, "output": "json", "limit": "1", "fl": "timestamp,original"})
            first = r.json()
            r2 = await get_client().get(
                "https://web.archive.org/cdx/search/cdx",
                params={"url": host, "output": "json", "limit": "-1", "fl": "timestamp,original"})
            last = r2.json()
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        res.node("domain", host, label=host)
        def fmt(rows):
            if len(rows) < 2: return None
            ts = rows[1][0]
            return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        if fmt(first): res.add("First snapshot", fmt(first), Confidence.CONFIRMED)
        if fmt(last): res.add("Latest snapshot", fmt(last), Confidence.CONFIRMED)
        res.add("Archive", f"https://web.archive.org/web/*/{host}", Confidence.INFO,
                link=f"https://web.archive.org/web/*/{host}")
        res.summary = f"Wayback history for {host}"
        return res


class ThreatFeeds(BaseModule):
    id = "threat_feeds"
    name = "Threat-feed check"
    description = "Cross-checks an IP against public abuse/threat blocklists (Feodo, Tor exits)."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.IP,)
    tier = "elite"
    timeout = 18.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        ip = _host_of(ctx.target)
        res.node("ip", ip, label=ip)
        hits = 0
        # Feodo Tracker (botnet C2 IPs)
        try:
            r = await get_client().get("https://feodotracker.abuse.ch/downloads/ipblocklist.txt")
            if ip in r.text:
                res.add("Feodo Tracker", "LISTED (botnet C2)", Confidence.LIKELY); hits += 1
            else:
                res.add("Feodo Tracker", "not listed", Confidence.CONFIRMED)
        except Exception:
            res.add("Feodo Tracker", "unavailable", Confidence.INFO)
        # Tor exit nodes
        try:
            r = await get_client().get("https://check.torproject.org/torbulkexitlist")
            if ip in r.text.split():
                res.add("Tor exit node", "YES", Confidence.LIKELY); hits += 1
            else:
                res.add("Tor exit node", "no", Confidence.CONFIRMED)
        except Exception:
            res.add("Tor exit node", "unavailable", Confidence.INFO)
        res.summary = f"{ip}: {hits} threat-feed hit(s)"
        return res


class TechFingerprint(BaseModule):
    id = "tech_fingerprint"
    name = "Tech fingerprint"
    description = "Guesses frameworks/CDN/analytics from headers and page markers."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.URL, InputType.DOMAIN)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        url = ctx.target if ctx.target.startswith("http") else f"https://{host}"
        try:
            r = await get_client().get(url)
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        body = r.text[:200000].lower()
        h = {k.lower(): v.lower() for k, v in r.headers.items()}
        tech = []
        markers = {
            "Cloudflare": "cf-ray" in h or "cloudflare" in h.get("server", ""),
            "Nginx": "nginx" in h.get("server", ""),
            "Apache": "apache" in h.get("server", ""),
            "WordPress": "wp-content" in body or "wp-includes" in body,
            "React": "__next" in body or "react" in body,
            "Next.js": "__next" in body or "next.js" in h.get("x-powered-by", ""),
            "Vue": "vue" in body and "data-v-" in body,
            "Google Analytics": "gtag(" in body or "google-analytics" in body,
            "Shopify": "cdn.shopify" in body,
            "Vercel": "vercel" in h.get("server", "") or "x-vercel-id" in h,
            "PHP": "php" in h.get("x-powered-by", ""),
        }
        res.node("domain", host, label=host)
        for name, hit in markers.items():
            if hit:
                tech.append(name); res.add("Detected", name, Confidence.LIKELY)
                res.node("tech", name, label=name)
        if not tech:
            res.add("Detected", "no obvious markers", Confidence.INFO)
        res.summary = f"Tech: {', '.join(tech) if tech else 'inconclusive'}"
        return res
