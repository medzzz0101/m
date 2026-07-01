"""intel.py — utilities, decoders, dorks and misc public lookups.

Small, sharp tools that don't fit the other domains: search-dork builders,
phone/MAC metadata, hash identification, encoders/decoders, JWT inspection,
IP/CIDR math, URL unshortening, and a couple of aggregation helpers.
"""
from __future__ import annotations

import base64
import re

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client


class GoogleDorks(BaseModule):
    id = "google_dorks"
    name = "Search-dork builder"
    description = "Generates ready-to-click advanced search queries for a target."
    category = Category.INTEL
    inputs = (InputType.DOMAIN, InputType.USERNAME, InputType.EMAIL, InputType.TEXT, InputType.URL)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        t = ctx.target.strip()
        dorks = [
            ("Exposed files", f'site:{t} (ext:pdf OR ext:xls OR ext:doc OR ext:txt)'),
            ("Login pages", f'site:{t} (inurl:login OR inurl:admin OR inurl:signin)'),
            ("Directory listing", f'site:{t} intitle:"index of"'),
            ("Config / env", f'site:{t} (ext:env OR ext:cfg OR ext:conf OR ext:ini)'),
            ("Mentions everywhere", f'"{t}"'),
            ("Pastebin mentions", f'site:pastebin.com "{t}"'),
            ("Public docs", f'"{t}" (site:docs.google.com OR site:scribd.com)'),
        ]
        for label, q in dorks:
            url = "https://www.google.com/search?q=" + q.replace(" ", "+").replace('"', "%22")
            res.add(label, q, Confidence.INFO, link=url)
        res.summary = f"{len(dorks)} search dorks for {t}"
        return res


class PhoneInfo(BaseModule):
    id = "phone_info"
    name = "Phone number metadata"
    description = "Country, carrier type and validity for a number — METADATA only, never owner."
    category = Category.INTEL
    inputs = (InputType.PHONE,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import phonenumbers
        from phonenumbers import geocoder, carrier, timezone
        res = self.result()
        try:
            num = phonenumbers.parse(ctx.target, None)
        except Exception:
            res.ok = False
            res.error = "could not parse (include country code, e.g. +1...)"
            return res
        valid = phonenumbers.is_valid_number(num)
        res.add("Valid", "yes" if valid else "no", Confidence.CONFIRMED)
        res.add("Country code", f"+{num.country_code}", Confidence.CONFIRMED)
        res.add("Region", geocoder.description_for_number(num, "en") or "—", Confidence.LIKELY)
        res.add("Carrier (type)", carrier.name_for_number(num, "en") or "—", Confidence.LIKELY)
        tz = timezone.time_zones_for_number(num)
        if tz: res.add("Timezone", ", ".join(tz), Confidence.LIKELY)
        ntype = phonenumbers.number_type(num)
        res.add("Line type", str(ntype).split(".")[-1] if hasattr(ntype, "name") else str(ntype),
                Confidence.INFO)
        res.add("Note", "carrier/region are metadata; this does NOT reveal the owner",
                Confidence.INFO)
        res.summary = f"+{num.country_code} · {geocoder.description_for_number(num,'en') or 'valid' if valid else 'invalid'}"
        return res


class MacLookup(BaseModule):
    id = "mac_lookup"
    name = "MAC vendor lookup"
    description = "Maps a MAC address OUI prefix to its hardware manufacturer."
    category = Category.INTEL
    inputs = (InputType.TEXT, InputType.HASH)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        mac = ctx.target.strip()
        if not re.match(r"^([0-9a-f]{2}[:\-]){2,5}[0-9a-f]{2}$", mac, re.I):
            res.ok = False; res.error = "not a MAC address"; return res
        try:
            r = await get_client().get(f"https://api.macvendors.com/{mac}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "No vendor for this MAC prefix"; return res
        res.add("MAC", mac, Confidence.CONFIRMED)
        res.add("Vendor", r.text, Confidence.CONFIRMED)
        res.summary = f"{mac} → {r.text}"
        return res


class HashIdentify(BaseModule):
    id = "hash_identify"
    name = "Hash identifier"
    description = "Identifies the likely algorithm of a hash by its length and shape."
    category = Category.INTEL
    inputs = (InputType.HASH, InputType.TEXT)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        h = ctx.target.strip()
        table = {32: ["MD5", "NTLM", "MD4"], 40: ["SHA-1", "RIPEMD-160"],
                 56: ["SHA-224"], 64: ["SHA-256", "SHA3-256"],
                 96: ["SHA-384"], 128: ["SHA-512", "SHA3-512"]}
        if not re.match(r"^[a-f0-9]+$", h, re.I):
            if re.match(r"^\$2[aby]\$", h): res.add("Type", "bcrypt", Confidence.CONFIRMED)
            elif h.startswith("$argon2"): res.add("Type", "Argon2", Confidence.CONFIRMED)
            else: res.add("Type", "not a hex hash", Confidence.INFO)
        else:
            cands = table.get(len(h))
            if cands:
                for c in cands: res.add("Candidate", c, Confidence.LIKELY)
            else:
                res.add("Length", f"{len(h)} hex chars — unrecognised", Confidence.INFO)
        res.summary = "Hash identification"
        return res


class Decoder(BaseModule):
    id = "decoder"
    name = "Encode / decode"
    description = "Base64, hex, URL and ROT13 decode of a string, all at once."
    category = Category.INTEL
    inputs = (InputType.TEXT, InputType.HASH)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import urllib.parse, codecs
        res = self.result()
        s = ctx.target
        try:
            b = base64.b64decode(s + "=" * (-len(s) % 4), validate=False)
            txt = b.decode("utf-8", "replace")
            if txt.isprintable(): res.add("Base64 →", txt[:300], Confidence.POSSIBLE)
        except Exception: pass
        try:
            if re.match(r"^[0-9a-f]+$", s, re.I) and len(s) % 2 == 0:
                res.add("Hex →", bytes.fromhex(s).decode("utf-8", "replace")[:300], Confidence.POSSIBLE)
        except Exception: pass
        if "%" in s:
            res.add("URL-decode →", urllib.parse.unquote(s)[:300], Confidence.POSSIBLE)
        res.add("ROT13 →", codecs.encode(s, "rot_13")[:300], Confidence.INFO)
        res.add("Base64 encode →", base64.b64encode(s.encode()).decode()[:300], Confidence.INFO)
        res.summary = "Decoded candidate representations"
        return res


class JwtDecode(BaseModule):
    id = "jwt_decode"
    name = "JWT inspector"
    description = "Decodes (does NOT verify) a JSON Web Token's header and claims."
    category = Category.INTEL
    inputs = (InputType.TEXT, InputType.HASH)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import json, datetime as dt
        res = self.result()
        parts = ctx.target.strip().split(".")
        if len(parts) < 2:
            res.ok = False; res.error = "not a JWT (expected header.payload.signature)"; return res
        def dec(seg):
            return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
        try:
            header = dec(parts[0]); payload = dec(parts[1])
        except Exception as e:
            res.ok = False; res.error = f"decode failed: {e}"; return res
        res.add("Algorithm", header.get("alg", "?"), Confidence.CONFIRMED)
        for k, v in payload.items():
            if k in ("exp", "iat", "nbf") and isinstance(v, (int, float)):
                v = f"{v} ({dt.datetime.utcfromtimestamp(v):%Y-%m-%d %H:%M} UTC)"
            res.add(f"claim: {k}", str(v)[:200], Confidence.INFO)
        res.add("Note", "signature NOT verified — decode only", Confidence.INFO)
        res.summary = f"JWT alg={header.get('alg','?')}, {len(payload)} claims"
        return res


class CidrCalc(BaseModule):
    id = "cidr_calc"
    name = "CIDR / subnet calc"
    description = "Network, broadcast, host range and count for an IP/CIDR block."
    category = Category.INTEL
    inputs = (InputType.TEXT, InputType.IP)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import ipaddress
        res = self.result()
        try:
            net = ipaddress.ip_network(ctx.target.strip(), strict=False)
        except Exception:
            res.ok = False; res.error = "not a valid IP/CIDR"; return res
        res.add("Network", str(net.network_address), Confidence.CONFIRMED)
        res.add("Netmask", str(net.netmask), Confidence.CONFIRMED)
        res.add("Broadcast", str(getattr(net, "broadcast_address", "—")), Confidence.CONFIRMED)
        res.add("Usable hosts", f"{max(net.num_addresses-2,0):,}", Confidence.CONFIRMED)
        res.add("Range", f"{net[0]} – {net[-1]}", Confidence.INFO)
        res.summary = f"{net} → {net.num_addresses:,} addresses"
        return res


class UrlUnshorten(BaseModule):
    id = "url_unshorten"
    name = "URL unshortener"
    description = "Follows a short link's redirect chain to its final destination."
    category = Category.INTEL
    inputs = (InputType.URL,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        try:
            r = await get_client().get(ctx.target)
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        for h in r.history:
            res.add(f"{h.status_code}", str(h.url), Confidence.INFO, link=str(h.url))
        res.add("Final URL", str(r.url), Confidence.CONFIRMED, link=str(r.url))
        res.node("url", str(r.url), label="destination")
        res.summary = f"{len(r.history)} redirect(s) → {r.url}"
        return res


class IpReputationList(BaseModule):
    id = "ip_droplist"
    name = "Spamhaus DROP check"
    description = "Checks an IP against Spamhaus DROP (hijacked/abused netblocks)."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.IP,)
    tier = "elite"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import ipaddress
        res = self.result()
        ip = ctx.target.strip()
        try:
            r = await get_client().get("https://www.spamhaus.org/drop/drop.txt")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        listed = None
        try:
            addr = ipaddress.ip_address(ip)
            for line in r.text.splitlines():
                line = line.split(";")[0].strip()
                if "/" in line and addr in ipaddress.ip_network(line, strict=False):
                    listed = line; break
        except Exception:
            pass
        res.node("ip", ip, label=ip)
        if listed:
            res.add("Spamhaus DROP", f"LISTED in {listed}", Confidence.LIKELY)
        else:
            res.add("Spamhaus DROP", "not listed", Confidence.CONFIRMED)
        res.summary = f"{ip}: {'listed' if listed else 'clean'} on DROP"
        return res


class UrlScan(BaseModule):
    id = "urlscan_search"
    name = "urlscan.io history"
    description = "Recent public urlscan.io scans referencing a domain (screenshots, IPs)."
    category = Category.INTEL
    inputs = (InputType.DOMAIN, InputType.URL)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = re.sub(r"^https?://", "", ctx.target).split("/")[0]
        try:
            r = await get_client().get("https://urlscan.io/api/v1/search/",
                                       params={"q": f"domain:{host}", "size": 10})
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "No urlscan data"; return res
        results = r.json().get("results", [])
        res.node("domain", host, label=host)
        for item in results[:10]:
            page = item.get("page", {})
            res.add(page.get("url", "scan"), page.get("ip", "—"), Confidence.INFO,
                    link=item.get("result"))
        res.summary = f"{len(results)} public urlscan results for {host}"
        return res


class RipeStat(BaseModule):
    id = "ripestat"
    name = "RIPEstat network info"
    description = "Authoritative ASN, prefix and holder info for an IP/prefix from RIPE."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.IP,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        ip = ctx.target.strip()
        try:
            r = await get_client().get(
                "https://stat.ripe.net/data/network-info/data.json", params={"resource": ip})
            info = r.json().get("data", {})
            r2 = await get_client().get(
                "https://stat.ripe.net/data/as-overview/data.json",
                params={"resource": (info.get("asns") or ["?"])[0]})
            asn = r2.json().get("data", {})
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        res.node("ip", ip, label=ip)
        res.add("Prefix", info.get("prefix", "—"), Confidence.CONFIRMED)
        for a in info.get("asns", []):
            res.add("ASN", f"AS{a}", Confidence.CONFIRMED)
        if asn.get("holder"): res.add("AS holder", asn["holder"], Confidence.CONFIRMED)
        res.summary = f"{ip} · {info.get('prefix','?')} · AS{(info.get('asns') or ['?'])[0]}"
        return res
