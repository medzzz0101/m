"""extra.py — a second wave of public-data modules.

Same guardrail as everywhere: public presence / public records / your own files
only. No deanonymisation, no private data, no third-party breach contents.
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


# ------------------------------------------------------------------ SOCIAL
class HackerNewsUser(BaseModule):
    id = "hn_user"
    name = "Hacker News profile (public)"
    description = "Public HN karma, account age and recent submissions via the Firebase API."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import datetime as dt
        res = self.result()
        user = ctx.target.lstrip("@")
        try:
            r = await get_client().get(f"https://hacker-news.firebaseio.com/v0/user/{user}.json")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        d = r.json()
        if not d:
            res.summary = "No public HN user"; return res
        res.node("username", user, label=f"HN:{user}")
        res.add("Karma", d.get("karma", 0), Confidence.CONFIRMED)
        if d.get("created"):
            res.add("Created", dt.datetime.utcfromtimestamp(d["created"]).strftime("%Y-%m-%d"), Confidence.CONFIRMED)
        res.add("Submissions", len(d.get("submitted", [])), Confidence.LIKELY,
                link=f"https://news.ycombinator.com/user?id={user}")
        if d.get("about"):
            res.add("About (self)", re.sub("<.*?>", " ", d["about"])[:200], Confidence.INFO)
        res.summary = f"HN {user}: {d.get('karma',0)} karma"
        return res


class LichessUser(BaseModule):
    id = "lichess_user"
    name = "Lichess profile (public)"
    description = "Public chess ratings, game count and activity from the open Lichess API."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@")
        try:
            r = await get_client().get(f"https://lichess.org/api/user/{user}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "No public Lichess user"; return res
        d = r.json()
        res.node("username", user, label=f"lichess:{user}")
        res.add("Games played", d.get("count", {}).get("all", 0), Confidence.CONFIRMED)
        perfs = d.get("perfs", {})
        for mode in ("blitz", "rapid", "bullet", "classical"):
            if perfs.get(mode, {}).get("games"):
                res.add(mode.title(), f"{perfs[mode]['rating']} ({perfs[mode]['games']} games)", Confidence.CONFIRMED)
        if d.get("profile", {}).get("country"):
            res.add("Country (self-set)", d["profile"]["country"], Confidence.INFO)
        res.summary = f"Lichess {user}: {d.get('count',{}).get('all',0)} games"
        return res


class ChessComUser(BaseModule):
    id = "chesscom_user"
    name = "Chess.com profile (public)"
    description = "Public Chess.com profile: name, country, join date via the open API."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import datetime as dt
        res = self.result()
        user = ctx.target.lstrip("@")
        try:
            r = await get_client().get(f"https://api.chess.com/pub/player/{user}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "No public Chess.com user"; return res
        d = r.json()
        res.node("username", user, label=f"chess.com:{user}")
        if d.get("name"): res.add("Name (self-set)", d["name"], Confidence.INFO)
        if d.get("country"): res.add("Country", d["country"].split("/")[-1], Confidence.INFO)
        if d.get("joined"):
            res.add("Joined", dt.datetime.utcfromtimestamp(d["joined"]).strftime("%Y-%m-%d"), Confidence.CONFIRMED)
        res.add("Followers", d.get("followers", 0), Confidence.CONFIRMED)
        res.summary = f"Chess.com {user}: {d.get('followers',0)} followers"
        return res


class NpmMaintainer(BaseModule):
    id = "npm_maintainer"
    name = "npm packages (public)"
    description = "Public npm packages authored/maintained by a username."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "elite"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@")
        try:
            r = await get_client().get(
                "https://registry.npmjs.org/-/v1/search",
                params={"text": f"maintainer:{user}", "size": 20})
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        objs = r.json().get("objects", []) if r.status_code == 200 else []
        if not objs:
            res.summary = "No public npm packages"; return res
        res.node("username", user, label=f"npm:{user}")
        for o in objs[:15]:
            pkg = o.get("package", {})
            res.add(pkg.get("name", "pkg"), f"v{pkg.get('version','?')} · {pkg.get('description','')[:50]}",
                    Confidence.CONFIRMED, link=pkg.get("links", {}).get("npm"))
        res.summary = f"{len(objs)} npm packages by {user}"
        return res


# ------------------------------------------------------------------ INFRA
class HttpHeadersFull(BaseModule):
    id = "http_headers_full"
    name = "All HTTP headers"
    description = "The complete raw set of response headers a host returns."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.URL, InputType.DOMAIN)
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
        for k, v in r.headers.items():
            res.add(k, v[:200], Confidence.INFO)
        res.summary = f"{len(r.headers)} response headers"
        return res


class DnsTwistLite(BaseModule):
    id = "dns_dumpster_lite"
    name = "DNS map (records + IPs)"
    description = "A compact DNS map: which IPs and mail hosts a domain uses."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import dns.asyncresolver
        res = self.result()
        host = _host_of(ctx.target)
        node = res.node("domain", host, label=host)
        resolver = dns.asyncresolver.Resolver(); resolver.lifetime = 6.0
        ips = set()
        for rtype in ("A", "AAAA"):
            try:
                for rr in await resolver.resolve(host, rtype):
                    ips.add(rr.to_text())
            except Exception:
                pass
        for ip in ips:
            res.add("Host IP", ip, Confidence.CONFIRMED, pivot=ip)
            ipn = res.node("ip", ip, label=ip); res.edge(node.id, ipn.id, "resolves_to")
        try:
            for rr in await resolver.resolve(host, "MX"):
                mx = rr.exchange.to_text().rstrip(".")
                res.add("Mail host", mx, Confidence.CONFIRMED, pivot=mx)
                mn = res.node("domain", mx, label=mx); res.edge(node.id, mn.id, "mail_for")
        except Exception:
            pass
        res.summary = f"{len(ips)} IPs mapped for {host}"
        return res


class SslLabsGrade(BaseModule):
    id = "tls_versions"
    name = "TLS versions & ciphers"
    description = "Which TLS protocol versions a host:443 accepts (security posture)."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.URL)
    tier = "elite"
    timeout = 25.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        import asyncio, ssl
        res = self.result()
        host = _host_of(ctx.target)
        res.node("domain", host, label=host)
        versions = {
            "TLS 1.3": ssl.TLSVersion.TLSv1_3,
            "TLS 1.2": ssl.TLSVersion.TLSv1_2,
            "TLS 1.1": ssl.TLSVersion.TLSv1_1,
            "TLS 1.0": ssl.TLSVersion.TLSv1,
        }
        from ..core.net import tls_supports
        # Sequential handshakes (parallel TLS is flaky behind some proxies).
        any_ok = False
        for name, ver in versions.items():
            ok = await asyncio.to_thread(tls_supports, host, ver, ver)
            any_ok = any_ok or ok
            weak = name in ("TLS 1.0", "TLS 1.1")
            res.add(name, "accepted" if ok else "rejected",
                    (Confidence.POSSIBLE if weak and ok else Confidence.CONFIRMED))
        if not any_ok:
            res.summary = f"No TLS handshake to {host}:443 (unreachable from here)"
        else:
            res.summary = f"TLS version probe for {host}"
        return res


class CryptoWallet(BaseModule):
    id = "btc_wallet"
    name = "Bitcoin address (public ledger)"
    description = "Public balance and transaction count for a BTC address (on-chain)."
    category = Category.INTEL
    inputs = (InputType.TEXT, InputType.HASH)
    tier = "elite"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        addr = ctx.target.strip()
        if not re.match(r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}$", addr):
            res.ok = False; res.error = "not a BTC address"; return res
        try:
            r = await get_client().get(f"https://mempool.space/api/address/{addr}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "Address not found on-chain"; return res
        d = r.json()
        cs = d.get("chain_stats", {})
        funded = cs.get("funded_txo_sum", 0); spent = cs.get("spent_txo_sum", 0)
        res.node("btc", addr, label=addr[:12] + "…")
        res.add("Balance", f"{(funded-spent)/1e8:.8f} BTC", Confidence.CONFIRMED)
        res.add("Total received", f"{funded/1e8:.8f} BTC", Confidence.CONFIRMED)
        res.add("Transactions", cs.get("tx_count", 0), Confidence.CONFIRMED,
                link=f"https://mempool.space/address/{addr}")
        res.summary = f"BTC {addr[:10]}…: {(funded-spent)/1e8:.4f} BTC, {cs.get('tx_count',0)} txs"
        return res


# ------------------------------------------------------------------ INTEL
class WhatIsMyTz(BaseModule):
    id = "ip_timezone_map"
    name = "IP → timezone & map"
    description = "Timezone, local time and map coordinates derived from an IP."
    category = Category.INTEL
    inputs = (InputType.IP,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        ip = _host_of(ctx.target)
        try:
            r = await get_client().get(f"https://ipwho.is/{ip}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        d = r.json()
        if not d.get("success"):
            res.summary = "No data for IP"; return res
        tz = d.get("timezone", {})
        res.node("ip", ip, label=ip)
        res.add("Timezone", tz.get("id", "—"), Confidence.LIKELY)
        res.add("Local time", tz.get("current_time", "—"), Confidence.LIKELY)
        res.add("UTC offset", tz.get("utc", "—"), Confidence.INFO)
        if d.get("latitude") is not None:
            res.extra["map"] = {"lat": d["latitude"], "lon": d["longitude"], "label": f"{ip} · {tz.get('id','')}"}
        res.summary = f"{ip}: {tz.get('id','?')} ({tz.get('utc','')})"
        return res


class WordCounter(BaseModule):
    id = "text_analyze"
    name = "Text analyzer"
    description = "Extracts emails, URLs, IPs, handles and hashes from any pasted text."
    category = Category.INTEL
    inputs = (InputType.TEXT,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        t = ctx.target
        patterns = {
            "Email": r"[\w.+-]+@[\w-]+\.[\w.-]+",
            "URL": r"https?://[^\s]+",
            "IPv4": r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
            "Handle": r"(?<!\w)@\w{2,30}",
            "BTC address": r"\b(?:bc1|[13])[a-zA-HJ-NP-Z0-9]{25,42}\b",
            "Hash": r"\b[a-f0-9]{32,64}\b",
        }
        total = 0
        for label, pat in patterns.items():
            found = sorted(set(re.findall(pat, t, re.I)))
            for f in found[:15]:
                res.add(label, f, Confidence.LIKELY, pivot=f)
                total += 1
        if not total:
            res.add("Result", "no structured indicators found", Confidence.INFO)
        res.summary = f"Extracted {total} indicators from text"
        return res


class QrDecode(BaseModule):
    id = "base_convert"
    name = "Number base converter"
    description = "Converts a value between binary, octal, decimal and hexadecimal."
    category = Category.INTEL
    inputs = (InputType.TEXT, InputType.HASH)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        s = ctx.target.strip()
        val = None
        for base, name in [(16, "hex"), (10, "dec"), (2, "bin"), (8, "oct")]:
            try:
                val = int(s, base); src = name; break
            except ValueError:
                continue
        if val is None:
            res.ok = False; res.error = "not a number in any common base"; return res
        res.add("Detected as", src, Confidence.LIKELY)
        res.add("Decimal", str(val), Confidence.CONFIRMED)
        res.add("Hex", hex(val), Confidence.CONFIRMED)
        res.add("Binary", bin(val), Confidence.CONFIRMED)
        res.add("Octal", oct(val), Confidence.CONFIRMED)
        if 0 <= val <= 0x10FFFF:
            try: res.add("As char", repr(chr(val)), Confidence.INFO)
            except Exception: pass
        res.summary = f"{s} = {val} (decimal)"
        return res
