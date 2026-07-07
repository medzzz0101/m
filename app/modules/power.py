"""power.py — extra free, keyless intelligence sources found while researching
how to make LIMBO stronger. All public, all legal (infrastructure/threat intel).

  * bgpview       — authoritative ASN / prefix / RIR data for an IP or ASN
  * threatminer   — passive DNS + related URIs/reports for a domain or IP
  * threatfox     — abuse.ch IOC database lookup (is this a known malware IOC?)
"""
from __future__ import annotations

import re

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client


def _host_of(target: str) -> str:
    t = re.sub(r"^https?://", "", target.strip(), flags=re.I)
    return t.split("/")[0].split(":")[0]


class BgpView(BaseModule):
    id = "bgpview"
    name = "BGPView ASN / prefix intel"
    description = "Authoritative ASN, prefix, RIR allocation and PTR for an IP (free, no key)."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.IP,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        ip = _host_of(ctx.target)
        res.node("ip", ip, label=ip)
        try:
            r = await get_client().get(f"https://api.bgpview.io/ip/{ip}")
        except Exception:
            res.add("BGPView", "source temporarily unreachable — try again shortly", Confidence.INFO)
            res.summary = "BGPView unavailable right now"; return res
        if r.status_code != 200:
            res.add("BGPView", f"no data (HTTP {r.status_code})", Confidence.INFO)
            res.summary = "No BGPView data"; return res
        d = r.json().get("data", {})
        node = res.node("ip", ip, label=ip)
        if d.get("ptr_record"): res.add("PTR", d["ptr_record"], Confidence.CONFIRMED, pivot=d["ptr_record"])
        for p in d.get("prefixes", [])[:6]:
            asn = p.get("asn", {})
            res.add("Prefix", f"{p.get('prefix','?')} · {p.get('name','')}", Confidence.CONFIRMED)
            if asn.get("asn"):
                res.add("ASN", f"AS{asn['asn']} · {asn.get('name','')} ({asn.get('country_code','')})",
                        Confidence.CONFIRMED, link=f"https://bgpview.io/asn/{asn['asn']}")
                res.node("asn", f"AS{asn['asn']}", label=asn.get("name", f"AS{asn['asn']}"))
        rir = (d.get("rir_allocation") or {})
        if rir.get("rir_name"):
            res.add("RIR", f"{rir['rir_name']} · allocated {rir.get('date_allocated','')[:10]}", Confidence.INFO)
        res.summary = f"{ip}: {len(d.get('prefixes',[]))} prefixes"
        return res


class ThreatMiner(BaseModule):
    id = "threatminer"
    name = "ThreatMiner passive DNS"
    description = "Passive-DNS history and related URIs for a domain or IP (free threat intel)."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.IP, InputType.URL)
    tier = "elite"
    timeout = 18.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        is_ip = ctx.input_type == InputType.IP
        base = "host.php" if is_ip else "domain.php"
        node = res.node("ip" if is_ip else "domain", host, label=host)
        # rt=2 → passive DNS
        try:
            r = await get_client().get(f"https://api.threatminer.org/v2/{base}",
                                       params={"q": host, "rt": "2"})
            data = r.json().get("results", []) if r.status_code == 200 else []
        except Exception:
            data = []
        seen = 0
        for row in data[:40]:
            if isinstance(row, dict):
                val = row.get("domain") or row.get("ip") or ""
                first = row.get("first_seen", "")[:10]
                if val:
                    res.add("passive DNS", f"{val} · {first}", Confidence.LIKELY, pivot=val)
                    seen += 1
        if not seen:
            res.summary = f"No ThreatMiner passive-DNS records for {host}"
        else:
            res.summary = f"{seen} passive-DNS records for {host}"
        return res


class ThreatFox(BaseModule):
    id = "threatfox"
    name = "ThreatFox IOC check"
    description = "Checks abuse.ch ThreatFox for a domain/IP being a known malware IOC."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.IP, InputType.URL)
    tier = "elite"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import json as _json
        res = self.result()
        host = _host_of(ctx.target)
        try:
            r = await get_client().post("https://threatfox-api.abuse.ch/api/v1/",
                                        content=_json.dumps({"query": "search_ioc", "search_term": host}))
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        d = r.json() if r.status_code == 200 else {}
        res.node("domain" if ctx.input_type != InputType.IP else "ip", host, label=host)
        if d.get("query_status") != "ok" or not d.get("data"):
            res.add("ThreatFox", "not a known IOC (clean)", Confidence.CONFIRMED)
            res.summary = f"{host}: clean on ThreatFox"
            return res
        for ioc in (d.get("data") or [])[:10]:
            res.add(ioc.get("malware_printable", "malware"),
                    f"{ioc.get('threat_type','')} · confidence {ioc.get('confidence_level','?')}%",
                    Confidence.LIKELY)
        res.summary = f"{host}: LISTED as IOC ({len(d['data'])} entries)"
        return res
