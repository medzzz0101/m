"""
modules/email_security.py
=========================
Deep email-authentication posture for a domain — the full stack that decides
whether someone can spoof mail "from" it:

  * SPF   (who may send)             * DMARC (policy + reporting)
  * DKIM  (common selector probing)  * MTA-STS + TLS-RPT (transport security)
  * BIMI  (brand indicator)          * DNSSEC (signed zone)

Each check is a DNS lookup; we grade the overall posture and explain every gap.
Complements dns_full with a focused, graded email view.
"""

from __future__ import annotations

import asyncio

import dns.resolver

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)

DKIM_SELECTORS = ["default", "google", "selector1", "selector2", "k1", "dkim",
                  "mail", "s1", "s2", "mandrill", "mailjet", "smtp"]


def _txt(name: str) -> list[str]:
    try:
        r = dns.resolver.Resolver(); r.lifetime = 4.0
        return [x.to_text().strip('"').replace('" "', "") for x in r.resolve(name, "TXT")]
    except Exception:
        return []


def _has(name: str, rtype: str) -> bool:
    try:
        r = dns.resolver.Resolver(); r.lifetime = 4.0
        r.resolve(name, rtype)
        return True
    except Exception:
        return False


class EmailSecurityModule(BaseModule):
    key = "email_security"
    name = "Email security posture"
    category = Category.INFRASTRUCTURE
    subtitle = "SPF/DMARC/DKIM/MTA-STS/BIMI"
    accepts = (InputType.DOMAIN,)
    needs_network = True
    description = (
        "Graded email-auth posture: SPF, DMARC (policy), DKIM selector probing, "
        "MTA-STS, TLS-RPT, BIMI and DNSSEC — with an explanation of every gap."
    )

    async def run(self, value: str, ctx: RunContext):
        d = value.lower().strip()
        loop = asyncio.get_running_loop()

        spf = await loop.run_in_executor(None, _txt, d)
        dmarc = await loop.run_in_executor(None, _txt, f"_dmarc.{d}")
        mta = await loop.run_in_executor(None, _txt, f"_mta-sts.{d}")
        tlsrpt = await loop.run_in_executor(None, _txt, f"_smtp._tls.{d}")
        bimi = await loop.run_in_executor(None, _txt, f"default._bimi.{d}")
        dnssec = await loop.run_in_executor(None, _has, d, "DNSKEY")
        dkim_hits = []
        for sel in DKIM_SELECTORS:
            if await loop.run_in_executor(None, _has, f"{sel}._domainkey.{d}", "TXT"):
                dkim_hits.append(sel)

        spf_rec = next((t for t in spf if "v=spf1" in t.lower()), None)
        dmarc_rec = next((t for t in dmarc if "v=dmarc1" in t.lower()), None)
        dmarc_policy = "none"
        if dmarc_rec:
            for part in dmarc_rec.split(";"):
                if part.strip().lower().startswith("p="):
                    dmarc_policy = part.split("=", 1)[1].strip()

        # Score the posture (0-100 good).
        score, gaps = 0, []
        if spf_rec: score += 20
        else: gaps.append("No SPF — anyone can claim to send as this domain.")
        if dmarc_rec:
            score += 20
            if dmarc_policy in ("quarantine", "reject"): score += 15
            else: gaps.append("DMARC p=none — spoofed mail is monitored but not blocked.")
        else: gaps.append("No DMARC — no anti-spoofing policy at all.")
        if dkim_hits: score += 15
        else: gaps.append("No DKIM selector found (probed common ones).")
        if mta: score += 10
        else: gaps.append("No MTA-STS — transport downgrade attacks possible.")
        if tlsrpt: score += 5
        if bimi: score += 5
        if dnssec: score += 10
        else: gaps.append("No DNSSEC — DNS answers unsigned.")
        grade = ("A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50
                 else "D" if score >= 30 else "F")

        findings = [
            {"label": "Email posture", "summary": f"Grade {grade} ({score}/100)",
             "confidence": "high" if score >= 70 else "medium"},
            {"label": "SPF", "summary": spf_rec or "missing",
             "confidence": "info" if spf_rec else "low"},
            {"label": "DMARC", "summary": (f"p={dmarc_policy} · {dmarc_rec}"
                                           if dmarc_rec else "missing"),
             "confidence": "info" if dmarc_policy in ("quarantine", "reject") else "low"},
            {"label": "DKIM selectors", "summary": ", ".join(dkim_hits) or "none found"},
            {"label": "MTA-STS", "summary": "present" if mta else "missing"},
            {"label": "TLS-RPT", "summary": "present" if tlsrpt else "missing"},
            {"label": "BIMI", "summary": "present" if bimi else "missing"},
            {"label": "DNSSEC", "summary": "signed" if dnssec else "unsigned"},
        ]
        if gaps:
            findings.append({"label": "Gaps", "values": gaps, "confidence": "medium"})

        return self.result(
            findings=findings,
            confidence=Confidence.HIGH,
            source_url=f"https://dmarcian.com/domain-checker/?domain={d}",
            raw={"score": score, "grade": grade, "spf": spf_rec, "dmarc": dmarc_rec,
                 "dkim": dkim_hits, "mta_sts": bool(mta), "dnssec": dnssec},
            nodes=[GraphNode("domain", d, props={"email_grade": grade})],
        )
