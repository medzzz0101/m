"""more.py — additional public-data modules (social + infra + intel).

Same guardrail as the rest of the suite: public presence / public records only.
Nothing here deanonymises a person or reads anyone's private data.
"""
from __future__ import annotations

import re
import socket

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client


def _host_of(target: str) -> str:
    t = re.sub(r"^https?://", "", target.strip(), flags=re.I)
    return t.split("/")[0].split(":")[0]


class GithubRepos(BaseModule):
    id = "github_repos"
    name = "GitHub repositories (public)"
    description = "Lists a user's most-starred public repositories and languages."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@")
        try:
            r = await get_client().get(
                f"https://api.github.com/users/{user}/repos",
                params={"sort": "pushed", "per_page": 30})
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code in (403, 429):
            res.add("GitHub API", "rate-limited on this host — try again shortly",
                    Confidence.INFO, link=f"https://github.com/{user}?tab=repositories")
            res.summary = "GitHub API rate-limited"
            return res
        if r.status_code != 200:
            res.summary = "No public repositories"; return res
        data = r.json()
        if not isinstance(data, list):
            res.summary = "No public repositories"; return res
        repos = sorted(data, key=lambda x: x.get("stargazers_count", 0), reverse=True)
        node = res.node("username", user, label=f"@{user}")
        langs: dict[str, int] = {}
        for repo in repos[:15]:
            langs[repo.get("language") or "—"] = langs.get(repo.get("language") or "—", 0) + 1
            res.add(repo["name"], f"★{repo.get('stargazers_count',0)} · {repo.get('language') or '—'}",
                    Confidence.CONFIRMED, link=repo.get("html_url"))
        top = ", ".join(f"{k}" for k, _ in sorted(langs.items(), key=lambda x: -x[1])[:4] if k != "—")
        res.summary = f"{len(repos)} repos · top langs: {top or 'n/a'}"
        return res


class GitlabUser(BaseModule):
    id = "gitlab_user"
    name = "GitLab profile (public)"
    description = "Public GitLab user id, name and activity via the open API."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@")
        try:
            r = await get_client().get(f"https://gitlab.com/api/v4/users?username={user}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        arr = r.json() if r.status_code == 200 else []
        if not arr:
            res.summary = "No public GitLab user"; return res
        d = arr[0]
        res.node("username", user, label=f"@{user}")
        res.add("Name", d.get("name", "—"), Confidence.CONFIRMED, link=d.get("web_url"))
        res.add("User ID", d.get("id", "—"), Confidence.CONFIRMED)
        res.add("State", d.get("state", "—"), Confidence.INFO)
        res.summary = f"GitLab: {d.get('name', user)}"
        return res


class EmailSecurity(BaseModule):
    id = "email_security"
    name = "Email security (SPF/DMARC)"
    description = "Reads a domain's public SPF, DMARC and MX records and grades them."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.URL)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import dns.asyncresolver
        res = self.result()
        host = _host_of(ctx.target)
        res.node("domain", host, label=host)
        resolver = dns.asyncresolver.Resolver(); resolver.lifetime = 6.0
        score = 0
        # SPF
        try:
            ans = await resolver.resolve(host, "TXT")
            spf = next((t.to_text().strip('"') for t in ans if "v=spf1" in t.to_text()), None)
            if spf: res.add("SPF", spf[:160], Confidence.CONFIRMED); score += 1
            else: res.add("SPF", "MISSING", Confidence.POSSIBLE)
        except Exception:
            res.add("SPF", "no TXT records", Confidence.INFO)
        # DMARC
        try:
            ans = await resolver.resolve(f"_dmarc.{host}", "TXT")
            dmarc = next((t.to_text().strip('"') for t in ans if "v=DMARC1" in t.to_text()), None)
            if dmarc:
                res.add("DMARC", dmarc[:160], Confidence.CONFIRMED); score += 1
                pol = re.search(r"p=(\w+)", dmarc)
                if pol: res.add("DMARC policy", pol.group(1),
                                Confidence.CONFIRMED if pol.group(1) != "none" else Confidence.POSSIBLE)
            else:
                res.add("DMARC", "MISSING", Confidence.POSSIBLE)
        except Exception:
            res.add("DMARC", "not published", Confidence.POSSIBLE)
        # MX
        try:
            ans = await resolver.resolve(host, "MX")
            for rr in ans:
                res.add("MX", rr.to_text(), Confidence.CONFIRMED)
            score += 1
        except Exception:
            res.add("MX", "none", Confidence.INFO)
        res.summary = f"Email security for {host}: {score}/3 protections present"
        return res


class ReverseDns(BaseModule):
    id = "reverse_dns"
    name = "Reverse DNS (PTR)"
    description = "The PTR hostname an IP resolves back to."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.IP,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        ip = _host_of(ctx.target)
        try:
            host, _, _ = socket.gethostbyaddr(ip)
        except Exception:
            res.summary = "No PTR record"; return res
        res.node("ip", ip, label=ip)
        res.add("PTR", host, Confidence.CONFIRMED, pivot=host)
        hn = res.node("domain", host, label=host)
        res.summary = f"{ip} → {host}"
        return res


class RobotsSitemap(BaseModule):
    id = "robots_sitemap"
    name = "robots.txt & sitemap"
    description = "Fetches robots.txt and any declared sitemaps — reveals hidden paths."
    category = Category.INTEL
    inputs = (InputType.DOMAIN, InputType.URL)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        try:
            r = await get_client().get(f"https://{host}/robots.txt")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200 or "<html" in r.text[:200].lower():
            res.summary = "No robots.txt"; return res
        res.node("domain", host, label=host)
        disallow = re.findall(r"(?im)^\s*Disallow:\s*(\S+)", r.text)
        sitemaps = re.findall(r"(?im)^\s*Sitemap:\s*(\S+)", r.text)
        for d in disallow[:25]:
            res.add("Disallow", d, Confidence.INFO)
        for s in sitemaps[:8]:
            res.add("Sitemap", s, Confidence.CONFIRMED, link=s)
        res.summary = f"{len(disallow)} disallow rules, {len(sitemaps)} sitemap(s)"
        return res


class UrlhausCheck(BaseModule):
    id = "urlhaus_check"
    name = "URLhaus malware check"
    description = "Checks abuse.ch URLhaus for known-malicious URLs on a host."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.URL, InputType.IP)
    tier = "elite"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        try:
            r = await get_client().post("https://urlhaus-api.abuse.ch/v1/host/",
                                        data={"host": host})
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        d = r.json() if r.status_code == 200 else {}
        res.node("domain", host, label=host)
        if d.get("query_status") != "ok":
            res.add("URLhaus", "not listed (clean)", Confidence.CONFIRMED)
            res.summary = f"{host}: clean on URLhaus"
            return res
        urls = d.get("urls", [])
        res.add("URLhaus", f"LISTED — {len(urls)} malicious URL(s)", Confidence.LIKELY)
        for u in urls[:8]:
            res.add(u.get("threat", "url"), u.get("url", "")[:90], Confidence.POSSIBLE)
        res.summary = f"{host}: {len(urls)} malicious URLs on URLhaus"
        return res


class Typosquat(BaseModule):
    id = "typosquat"
    name = "Typosquat generator"
    description = "Generates look-alike domains and checks which currently resolve."
    category = Category.INTEL
    inputs = (InputType.DOMAIN,)
    tier = "premium"
    timeout = 20.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        name, _, tld = host.partition(".")
        if not tld:
            res.ok = False; res.error = "need a full domain"; return res
        variants = set()
        for i in range(len(name)):
            variants.add(name[:i] + name[i+1:] + "." + tld)               # deletion
            for c in "aeiou":
                variants.add(name[:i] + c + name[i:] + "." + tld)          # insertion
        subs = {"o": "0", "l": "1", "i": "1", "e": "3", "a": "@"}
        for a, b in subs.items():
            if a in name:
                variants.add(name.replace(a, b, 1) + "." + tld)
        variants.discard(host)
        node = res.node("domain", host, label=host)
        cand = list(variants)[:24]

        # Resolve concurrently in threads so we never block the event loop.
        import asyncio
        async def resolves(v):
            try:
                await asyncio.to_thread(socket.gethostbyname, v)
                return v
            except Exception:
                return None
        hits = [v for v in await asyncio.gather(*(resolves(v) for v in cand)) if v]
        for v in hits:
            res.add(v, "RESOLVES (registered)", Confidence.LIKELY, pivot=v, link=f"https://{v}")
        res.summary = f"{len(hits)} of {len(cand)} look-alike domains resolve"
        return res


class DnsHistoryHackertarget(BaseModule):
    id = "reverse_ip_hosts"
    name = "Reverse-IP co-hosted sites"
    description = "Other domains sharing the same server IP (public HackerTarget data)."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.IP, InputType.DOMAIN)
    tier = "elite"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        ip = host
        if ctx.input_type != InputType.IP:
            try: ip = socket.gethostbyname(host)
            except Exception: pass
        try:
            r = await get_client().get(f"https://api.hackertarget.com/reverseiplookup/?q={ip}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        text = r.text.strip()
        if "error" in text.lower() or "API count" in text:
            res.summary = "Reverse-IP unavailable (public quota)"; return res
        node = res.node("ip", ip, label=ip)
        hosts = [h.strip() for h in text.splitlines() if h.strip()][:40]
        for h in hosts:
            res.add("co-hosted", h, Confidence.LIKELY, pivot=h, link=f"https://{h}")
            hn = res.node("domain", h, label=h); res.edge(node.id, hn.id, "hosted_on")
        res.summary = f"{len(hosts)} domains share IP {ip}"
        return res


class DomainReputation(BaseModule):
    id = "domain_reputation"
    name = "Domain age & reputation"
    description = "Domain creation date and a simple trust signal from public records."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import datetime as dt
        res = self.result()
        host = _host_of(ctx.target)
        try:
            r = await get_client().get(f"https://rdap.org/domain/{host}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "No RDAP data"; return res
        d = r.json()
        res.node("domain", host, label=host)
        reg = next((e.get("eventDate") for e in d.get("events", [])
                    if e.get("eventAction") == "registration"), None)
        if reg:
            created = dt.datetime.fromisoformat(reg.replace("Z", "+00:00"))
            age_days = (dt.datetime.now(dt.timezone.utc) - created).days
            res.add("Registered", reg[:10], Confidence.CONFIRMED)
            res.add("Age", f"{age_days//365}y {(age_days%365)//30}m ({age_days} days)", Confidence.CONFIRMED)
            trust = "established" if age_days > 365 else "young — extra caution" if age_days > 30 else "very new — high caution"
            res.add("Trust signal", trust,
                    Confidence.LIKELY if age_days > 365 else Confidence.POSSIBLE)
        statuses = d.get("status", [])
        if statuses: res.add("Status", ", ".join(statuses)[:120], Confidence.INFO)
        res.summary = f"{host}: {'registered ' + reg[:10] if reg else 'age unknown'}"
        return res
