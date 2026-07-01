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

        # 2. Breaches affecting the domain (public catalogue, no key).
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
