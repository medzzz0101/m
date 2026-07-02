"""recon.py — heavy-hitter passive recon, inspired by Amass / theHarvester.

These aggregate MANY public sources for a bigger picture, the way the classic
OSINT tools do — but strictly passively and from public data:

  * subdomain_enum   — Amass-style: union of several free CT / passive-DNS feeds
  * email_harvest    — theHarvester-style: public org emails from PGP keyservers
                       and the domain's own published pages (never third parties)

GUARDRAIL: this harvests only PUBLICLY-PUBLISHED organisational data (certs a
company issued, subdomains in public CT logs, emails the org put on its own site
or a public keyserver). It does not touch private individuals' data.
"""
from __future__ import annotations

import asyncio
import re

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client


def _host_of(target: str) -> str:
    t = re.sub(r"^https?://", "", target.strip(), flags=re.I)
    return t.split("/")[0].split(":")[0]


class SubdomainEnum(BaseModule):
    id = "subdomain_enum"
    name = "Subdomain enum (multi-source)"
    description = "Amass-style: unions crt.sh, certspotter, HackerTarget, OTX & Anubis for max coverage."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.URL)
    tier = "premium"
    timeout = 28.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        subs: set[str] = set()
        sources_ok: list[str] = []

        async def crtsh():
            r = await get_client().get(f"https://crt.sh/?q=%25.{host}&output=json", timeout=16)
            if r.status_code == 200 and r.text.strip().startswith("["):
                for row in r.json():
                    for nm in str(row.get("name_value", "")).split("\n"):
                        _add(nm)
                return "crt.sh"

        async def certspotter():
            r = await get_client().get(
                "https://api.certspotter.com/v1/issuances",
                params={"domain": host, "include_subdomains": "true", "expand": "dns_names"}, timeout=14)
            if r.status_code == 200:
                for row in r.json():
                    for nm in row.get("dns_names", []):
                        _add(nm)
                return "certspotter"

        async def hackertarget():
            r = await get_client().get(f"https://api.hackertarget.com/hostsearch/?q={host}", timeout=12)
            if r.status_code == 200 and "," in r.text and "API count" not in r.text:
                for line in r.text.splitlines():
                    _add(line.split(",")[0])
                return "hackertarget"

        async def otx():
            r = await get_client().get(
                f"https://otx.alienvault.com/api/v1/indicators/domain/{host}/passive_dns", timeout=14)
            if r.status_code == 200:
                for row in r.json().get("passive_dns", []):
                    _add(row.get("hostname", ""))
                return "otx"

        async def anubis():
            r = await get_client().get(f"https://jldc.me/anubis/subdomains/{host}", timeout=12)
            if r.status_code == 200 and r.text.strip().startswith("["):
                for nm in r.json():
                    _add(nm)
                return "anubis"

        def _add(nm: str):
            nm = (nm or "").strip().lstrip("*.").lower()
            if nm and nm.endswith(host) and "@" not in nm:
                subs.add(nm)

        results = await asyncio.gather(crtsh(), certspotter(), hackertarget(), otx(), anubis(),
                                       return_exceptions=True)
        sources_ok = [r for r in results if isinstance(r, str)]

        dnode = res.node("domain", host, label=host)
        for s in sorted(subs)[:120]:
            res.add("subdomain", s, Confidence.LIKELY, pivot=s, link=f"https://{s}")
            sn = res.node("subdomain", s, label=s); res.edge(dnode.id, sn.id, "subdomain_of")
        res.extra["count"] = len(subs)
        res.summary = (f"{len(subs)} unique subdomains from {len(sources_ok)} sources "
                       f"({', '.join(sources_ok) or 'none reachable'})")
        return res


class EmailHarvest(BaseModule):
    id = "email_harvest"
    name = "Public email harvest (domain)"
    description = "theHarvester-style: org emails from public PGP keyservers + the domain's own pages."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.URL)
    tier = "elite"
    timeout = 20.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        emails: dict[str, str] = {}   # email -> source
        pat = re.compile(rf"[a-zA-Z0-9._%+\-]+@(?:[a-zA-Z0-9\-]+\.)*{re.escape(host)}", re.I)

        # Source 1: public PGP keyserver (Ubuntu) — index search by domain.
        try:
            r = await get_client().get("https://keyserver.ubuntu.com/pks/lookup",
                                       params={"search": f"@{host}", "op": "index", "fingerprint": "on"},
                                       timeout=12)
            if r.status_code == 200:
                for m in pat.findall(r.text):
                    emails[m.lower()] = "PGP keyserver"
        except Exception:
            pass

        # Source 2: the domain's own public pages (homepage + common contact pages).
        for path in ("", "/contact", "/about", "/contact-us", "/impressum"):
            try:
                r = await get_client().get(f"https://{host}{path}", timeout=8)
                if r.status_code == 200:
                    for m in pat.findall(r.text):
                        emails.setdefault(m.lower(), "public page")
            except Exception:
                continue

        dnode = res.node("domain", host, label=host)
        for em, src in sorted(emails.items()):
            res.add(em, f"public · {src}", Confidence.LIKELY, pivot=em)
            en = res.node("email", em, label=em); res.edge(dnode.id, en.id, "contact_of")
        if not emails:
            res.summary = f"No public org emails found for {host}"
        else:
            res.summary = f"{len(emails)} public organisational email(s) for {host}"
        res.add("Scope note", "org-published addresses only — not private individuals", Confidence.INFO)
        return res
