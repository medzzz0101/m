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

        # 2. Per-EMAIL breach check — AGGREGATED across multiple free sources for
        #    broad coverage. We collect only the NAMES of breaches (and dates /
        #    data-type categories) — never passwords or any leaked value.
        breaches: dict[str, str] = {}   # name -> date/label
        data_types: set[str] = set()
        risk_label = None

        # 2a. XposedOrNot (breach names).
        try:
            xon = await fetch_json(
                ctx, f"https://api.xposedornot.com/v1/check-email/{email}",
                ttl=3600, namespace="xon",
                headers={"User-Agent": "osint-engine-self-exposure"})
            if isinstance(xon, dict) and xon.get("breaches"):
                for sub in xon["breaches"]:            # flatten all sub-lists
                    for name in (sub or []):
                        if name:
                            breaches.setdefault(name, "")
        except Exception:
            pass

        # 2b. LeakCheck public (sources: name + date) — a different, large dataset.
        try:
            lc = await fetch_json(
                ctx, f"https://leakcheck.io/api/public?check={email}",
                ttl=3600, namespace="leakcheck",
                headers={"User-Agent": "osint-engine-self-exposure"})
            if isinstance(lc, dict):
                for s in lc.get("sources", []) or []:
                    nm = s.get("name")
                    if nm:
                        breaches[nm] = s.get("date", "") or breaches.get(nm, "")
                for f in lc.get("fields", []) or []:
                    data_types.add(f)
        except Exception:
            pass

        # 2c. XposedOrNot analytics (risk level + exposed data categories).
        try:
            an = await fetch_json(
                ctx, f"https://api.xposedornot.com/v1/breach-analytics?email={email}",
                ttl=3600, namespace="xon_an",
                headers={"User-Agent": "osint-engine-self-exposure"})
            risk = (((an or {}).get("BreachMetrics") or {}).get("risk") or [{}])
            risk_label = risk[0].get("risk_label") if risk else None
            for b in (((an or {}).get("ExposedBreaches") or {})
                      .get("breaches_details") or []):
                for d in (b.get("xposed_data", "") or "").split(";"):
                    if d:
                        data_types.add(d)
        except Exception:
            pass

        if breaches:
            listed = sorted(f"{n}{f'  ({d})' if d else ''}"
                            for n, d in breaches.items())
            findings.append({
                "label": "⚠ This email appears in breaches",
                "summary": f"{len(breaches)} breach(es) across free sources — "
                           "change reused passwords & enable 2FA",
                "values": listed,
                "confidence": "high"})
        else:
            findings.append({"label": "This email in breaches",
                             "summary": "Not found in the free breach sources — "
                                        "good news (a paid HIBP key checks more).",
                             "confidence": "info"})
        if risk_label:
            findings.append({"label": "Risk level", "summary": risk_label})
        if data_types:
            findings.append({"label": "Types of data exposed (categories)",
                             "values": sorted(data_types)[:24],
                             "note": "Categories only — passwords/values are never "
                                     "retrieved."})
        raw["breach_sources"] = {"count": len(breaches),
                                 "names": sorted(breaches)}

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

        # 3. Optional EXTRA source: if an HIBP key is configured, add its official
        #    per-address result too. Without a key we already checked the address
        #    above via the free sources, so we DON'T nag — we just note it quietly.
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
                        "label": "HIBP (official) breaches",
                        "summary": f"{len(data)} breach(es)",
                        "values": [b.get("Title") for b in data],
                        "confidence": "high"})
                elif acct.status_code == 404:
                    findings.append({"label": "HIBP (official)",
                                     "summary": "not found in HaveIBeenPwned."})
            except Exception:
                pass

        nodes = [GraphNode("email", email, props={"domain": domain}),
                 GraphNode("domain", domain)]
        return self.result(findings=findings, confidence=Confidence.INFO,
                           source_url=f"https://haveibeenpwned.com/",
                           raw=raw, nodes=nodes)
