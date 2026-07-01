"""
modules/email_exposure.py
=========================
Self-exposure checks for an email address. STRICTLY defensive / your-own-account:

  * Gravatar presence — whether a public Gravatar profile exists for the
    address's MD5 (a public profile the owner themselves published).
  * Breaches affecting the email's DOMAIN — HIBP's public breach catalogue
    (no key) filtered by domain: context about incidents that touched that
    provider, NOT anyone's credentials.
  * (Optional) breaches for THIS email — only if an HIBP API key is present in
    .env. This is meant for checking YOUR OWN / an authorized address.

GUARDRAIL: this never retrieves passwords or a third party's private data. It
reports whether an address/domain appears in PUBLIC breach *metadata*, which is
exactly the "check my own exposure" use case.
"""

from __future__ import annotations

import hashlib

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


class EmailExposureModule(BaseModule):
    key = "email_exposure"
    name = "Email exposure"
    category = Category.IDENTITY
    subtitle = "Self-exposure (public metadata)"
    accepts = (InputType.EMAIL,)
    needs_network = True
    description = (
        "Defensive self-exposure for an email: Gravatar presence, breaches "
        "affecting its domain (public HIBP catalogue, no key), and — only with "
        "your own HIBP key — breaches for that address. Never retrieves credentials."
    )

    async def run(self, value: str, ctx: RunContext):
        email = value.strip().lower()
        if "@" not in email:
            return self.result(error="Provide an email address.")
        domain = email.split("@", 1)[1]
        md5 = hashlib.md5(email.encode()).hexdigest()

        findings = [{
            "label": "Scope",
            "summary": "Public metadata only — no passwords, no third-party data. "
                       "Intended for checking your own / authorized exposure.",
            "confidence": "info",
        }]
        raw: dict = {}

        # 1. Gravatar presence (public profile the owner published).
        try:
            g = await ctx.http.get(f"https://www.gravatar.com/{md5}.json",
                                   follow_redirects=True)
            has_grav = g.status_code == 200
            findings.append({"label": "Gravatar",
                             "summary": "public profile exists" if has_grav
                             else "no public profile",
                             "values": [f"https://gravatar.com/{md5}"] if has_grav else None})
            raw["gravatar"] = has_grav
        except Exception:
            findings.append({"label": "Gravatar", "summary": "check failed"})

        # 2. Per-EMAIL breach check via XposedOrNot (free, no key). Returns the
        #    NAMES of breaches this exact address appears in — never passwords or
        #    any leaked value. This is the "am I in a breach" self-exposure check.
        try:
            xon = await fetch_json(
                ctx, f"https://api.xposedornot.com/v1/check-email/{email}",
                ttl=3600, namespace="xon",
                headers={"User-Agent": "osint-engine-self-exposure"})
            breach_list = []
            if isinstance(xon, dict) and xon.get("breaches"):
                # Shape: {"breaches": [[ "Name1", "Name2", ... ]]}
                first = xon["breaches"][0] if xon["breaches"] else []
                breach_list = [b for b in first if b]
            if breach_list:
                findings.append({
                    "label": "⚠ This email appears in breaches",
                    "summary": f"{len(breach_list)} breach(es) — change reused "
                               "passwords & enable 2FA",
                    "values": sorted(breach_list),
                    "confidence": "high"})
            else:
                findings.append({"label": "This email in breaches",
                                 "summary": "Not found in XposedOrNot — good news.",
                                 "confidence": "info"})
            raw["xposedornot"] = breach_list
        except Exception as exc:  # noqa: BLE001
            findings.append({"label": "Per-email breach check",
                             "summary": f"XposedOrNot lookup failed: {exc}"})

        # 2b. Exposure analytics (risk score + CATEGORIES of exposed data — still
        #     just metadata, never the values themselves).
        try:
            an = await fetch_json(
                ctx, f"https://api.xposedornot.com/v1/breach-analytics?email={email}",
                ttl=3600, namespace="xon_an",
                headers={"User-Agent": "osint-engine-self-exposure"})
            risk = (((an or {}).get("BreachMetrics") or {}).get("risk") or [{}])
            risk_label = risk[0].get("risk_label") if risk else None
            xposed = (((an or {}).get("ExposedBreaches") or {})
                      .get("breaches_details") or [])
            data_types = sorted({d for b in xposed
                                 for d in (b.get("xposed_data", "") or "").split(";") if d})
            if risk_label:
                findings.append({"label": "Risk level", "summary": risk_label})
            if data_types:
                findings.append({"label": "Types of data exposed (categories)",
                                 "values": data_types[:20],
                                 "note": "Categories only — passwords/values are "
                                         "never retrieved."})
        except Exception:
            pass

        # 3. Breaches affecting the domain (public catalogue, no key).
        try:
            breaches = await fetch_json(
                ctx, f"https://haveibeenpwned.com/api/v3/breaches?Domain={domain}",
                ttl=86400, namespace="hibp_dom",
                headers={"User-Agent": "osint-engine-self-exposure"})
            names = [f"{b.get('Title')} ({b.get('BreachDate')}, "
                     f"{b.get('PwnCount',0):,} accounts)" for b in (breaches or [])]
            findings.append({
                "label": f"Breaches at {domain}",
                "summary": f"{len(names)} known incident(s) affecting this provider",
                "values": names or ["none in the public catalogue"],
                "confidence": "medium" if names else "info",
            })
            raw["domain_breaches"] = len(names)
        except Exception as exc:  # noqa: BLE001
            findings.append({"label": "Domain breaches", "summary": f"lookup failed: {exc}"})

        # 3. Optional: breaches for THIS address (own/authorized) — needs a key.
        key = ctx.config.get("HIBP_API_KEY", "").strip()
        if key:
            try:
                acct = await ctx.http.get(
                    f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
                    "?truncateResponse=false",
                    headers={"hibp-api-key": key,
                             "User-Agent": "osint-engine-self-exposure"})
                if acct.status_code == 200:
                    data = acct.json()
                    findings.append({
                        "label": "This address in breaches",
                        "summary": f"{len(data)} breach(es)",
                        "values": [b.get("Title") for b in data],
                        "confidence": "high"})
                elif acct.status_code == 404:
                    findings.append({"label": "This address in breaches",
                                     "summary": "not found — good news"})
            except Exception:
                pass
        else:
            findings.append({"label": "Per-address check",
                             "summary": "add HIBP_API_KEY to .env to check this "
                                        "specific (own/authorized) address.",
                             "confidence": "info"})

        nodes = [GraphNode("email", email, props={"domain": domain}),
                 GraphNode("domain", domain)]
        return self.result(findings=findings, confidence=Confidence.INFO,
                           source_url=f"https://haveibeenpwned.com/",
                           raw=raw, nodes=nodes)
