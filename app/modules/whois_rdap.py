"""
modules/whois_rdap.py
=====================
Registration data for a domain via RDAP (the modern, JSON, rate-friendly
successor to classic WHOIS). We query the IANA RDAP bootstrap so we don't need
to know each TLD's server.

RDAP returns structured registrar/registration/expiry data and registration
events. It is PUBLIC infrastructure metadata — registrant personal details are
almost always redacted by GDPR/registrars, which is exactly the boundary we
want to stay on.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


def _events(obj: dict) -> dict[str, str]:
    """Flatten RDAP 'events' [{eventAction, eventDate}] into a dict."""
    out = {}
    for ev in obj.get("events", []) or []:
        action = ev.get("eventAction")
        date = ev.get("eventDate")
        if action and date:
            out[action] = date
    return out


def _registrar(obj: dict) -> str | None:
    """Pull the registrar name out of RDAP's vCard-ish entity structure."""
    for ent in obj.get("entities", []) or []:
        roles = ent.get("roles", []) or []
        if "registrar" in roles:
            # vcardArray = ["vcard", [ ["fn", {}, "text", "NAME"], ... ]]
            vcard = ent.get("vcardArray")
            if vcard and len(vcard) > 1:
                for item in vcard[1]:
                    if item and item[0] == "fn":
                        return item[3]
            return ent.get("handle")
    return None


class WhoisRdapModule(BaseModule):
    key = "whois"
    name = "WHOIS / RDAP"
    category = Category.INFRASTRUCTURE
    subtitle = "Registrar, dates, status"
    accepts = (InputType.DOMAIN,)
    needs_network = True
    description = (
        "Domain registration data via RDAP (structured WHOIS). Registrar, "
        "creation/expiry, and status flags — public infrastructure metadata."
    )

    async def run(self, value: str, ctx: RunContext):
        domain = value.lower().strip()
        # IANA's bootstrap RDAP resolver redirects to the right TLD server.
        url = f"https://rdap.org/domain/{domain}"

        try:
            # rdap.org 302-redirects to the authoritative TLD server, so we
            # must follow redirects (the shared client defaults to NOT following).
            data = await fetch_json(ctx, url, ttl=86400, namespace="rdap",
                                    follow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            return self.result(
                error=f"RDAP lookup failed: {type(exc).__name__}: {exc}",
                source_url=url,
            )

        events = _events(data)
        registrar = _registrar(data)
        statuses = data.get("status", []) or []
        nameservers = [ns.get("ldhName") for ns in data.get("nameservers", []) or []
                       if ns.get("ldhName")]

        findings = [
            {"label": "Registrar", "summary": registrar or "—"},
            {"label": "Registered", "summary": events.get("registration", "—")},
            {"label": "Expires", "summary": events.get("expiration", "—")},
            {"label": "Last changed", "summary": events.get("last changed", "—")},
            {"label": "Status", "values": statuses or ["—"]},
        ]
        if nameservers:
            findings.append({"label": "Nameservers", "values": nameservers})

        nodes = [GraphNode("domain", domain,
                           props={"registrar": registrar,
                                  "registered": events.get("registration")})]
        if registrar:
            nodes.append(GraphNode("org", registrar, label=registrar,
                                   props={"role": "registrar"}))

        return self.result(
            findings=findings,
            confidence=Confidence.HIGH,
            source_url=f"https://rdap.org/domain/{domain}",
            raw=data,
            nodes=nodes,
        )
