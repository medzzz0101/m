"""
modules/exposure_score.py
=========================
A per-target EXPOSURE SCORE: a single 0–100 number (higher = more exposed) built
from weighted, explained signals so it's never a black box. It gathers a few
lightweight signals itself so it can stand alone as a module:

  * Shodan InternetDB  -> open ports (surface) and known CVEs (heavy weight)
  * DNS email-auth     -> missing SPF / DMARC / DNSSEC (spoofing risk)
  * HTTP headers       -> missing HSTS / CSP (web-hardening gaps)

Every factor lists WHY it added points, so the score is auditable. This is a
defensive posture summary, not a vulnerability scan.
"""

from __future__ import annotations

import asyncio

import dns.resolver

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json, resolve_ip, host_of


def _txt(domain: str, name: str = "") -> list[str]:
    try:
        r = dns.resolver.Resolver()
        r.lifetime = 4.0
        target = f"{name}.{domain}" if name else domain
        return [x.to_text().strip('"') for x in r.resolve(target, "TXT")]
    except Exception:
        return []


def _has(domain: str, rtype: str) -> bool:
    try:
        r = dns.resolver.Resolver(); r.lifetime = 4.0
        r.resolve(domain, rtype)
        return True
    except Exception:
        return False


class ExposureScoreModule(BaseModule):
    key = "exposure_score"
    name = "Exposure score"
    category = Category.INTEL
    subtitle = "Weighted risk summary"
    accepts = (InputType.DOMAIN, InputType.IP)
    needs_network = True
    description = (
        "A single, explained 0–100 exposure score from open ports, known CVEs, "
        "missing email-auth (SPF/DMARC/DNSSEC) and web-hardening headers."
    )

    async def run(self, value: str, ctx: RunContext):
        target = value.strip().lower()
        is_domain = "." in target and not target.replace(".", "").isdigit()
        ip = await resolve_ip(target)

        score = 0
        factors: list[dict] = []   # {label, points, detail}

        # --- Signal 1: Shodan InternetDB (ports + CVEs) --------------------
        if ip:
            try:
                sh = await fetch_json(ctx, f"https://internetdb.shodan.io/{ip}",
                                      ttl=21600, namespace="shodan")
                ports = sh.get("ports", []) or []
                vulns = sh.get("vulns", []) or []
                if ports:
                    pts = min(20, len(ports) * 3)
                    score += pts
                    factors.append({"label": "Open ports", "points": pts,
                                    "detail": f"{len(ports)} exposed: {ports}"})
                if vulns:
                    pts = min(40, len(vulns) * 10)
                    score += pts
                    factors.append({"label": "Known CVEs", "points": pts,
                                    "detail": f"{len(vulns)}: {vulns[:6]}"})
            except Exception:
                pass

        # --- Signal 2: DNS email-authentication (domains only) -------------
        if is_domain:
            loop = asyncio.get_running_loop()
            spf = await loop.run_in_executor(None, _txt, target)
            dmarc = await loop.run_in_executor(None, _txt, target, "_dmarc")
            dnssec = await loop.run_in_executor(None, _has, target, "DNSKEY")
            if not any("v=spf1" in t.lower() for t in spf):
                score += 10
                factors.append({"label": "No SPF", "points": 10,
                                "detail": "Domain can be more easily spoofed in email."})
            if not dmarc:
                score += 10
                factors.append({"label": "No DMARC", "points": 10,
                                "detail": "No policy telling receivers to reject spoofs."})
            if not dnssec:
                score += 5
                factors.append({"label": "No DNSSEC", "points": 5,
                                "detail": "DNS answers aren't cryptographically signed."})

        # --- Signal 3: HTTP hardening headers ------------------------------
        if is_domain:
            try:
                resp = await ctx.http.get(f"https://{target}", follow_redirects=True,
                                          headers={"User-Agent": "osint-exposure"})
                if "strict-transport-security" not in resp.headers:
                    score += 8
                    factors.append({"label": "No HSTS", "points": 8,
                                    "detail": "Browsers not forced onto HTTPS."})
                if "content-security-policy" not in resp.headers:
                    score += 7
                    factors.append({"label": "No CSP", "points": 7,
                                    "detail": "No content-security-policy header."})
            except Exception:
                pass

        score = min(100, score)
        band = ("Low" if score < 25 else "Moderate" if score < 50
                else "Elevated" if score < 75 else "High")

        findings = [
            {"label": "Exposure score", "summary": f"{score} / 100 · {band}",
             "confidence": "high" if score >= 50 else "info"},
        ]
        for f in sorted(factors, key=lambda x: -x["points"]):
            findings.append({"label": f"+{f['points']}  {f['label']}",
                             "summary": f["detail"]})
        if not factors:
            findings.append({"label": "Result",
                             "summary": "No notable exposure signals gathered "
                                        "(or target not reachable)."})

        nodes = [GraphNode("domain" if is_domain else "ip", target,
                           props={"exposure_score": score})]
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if score >= 50 else Confidence.INFO,
            raw={"score": score, "band": band, "factors": factors}, nodes=nodes,
        )
