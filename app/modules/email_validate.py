"""email_validate.py — non-intrusive email validity & hygiene checks.

Tells you whether an email is well-formed, has a real mail server (MX), uses a
disposable/temporary provider, or is a role account (info@, admin@…). It never
emails the person and never probes their mailbox — purely public DNS + format.
"""
from __future__ import annotations

import re

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)

_DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "temp-mail.org",
    "tempmail.com", "yopmail.com", "trashmail.com", "getnada.com", "dispostable.com",
    "sharklasers.com", "throwawaymail.com", "maildrop.cc", "fakeinbox.com",
    "mohmal.com", "emailondeck.com", "mailnesia.com", "tempinbox.com", "burnermail.io",
}
_ROLE = {"admin", "info", "support", "contact", "sales", "help", "noreply",
         "no-reply", "webmaster", "postmaster", "hello", "team", "office", "billing"}
_FREE = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
         "proton.me", "protonmail.com", "gmx.com", "aol.com", "yandex.com"}


class EmailValidate(BaseModule):
    id = "email_validate"
    name = "Email validity & hygiene"
    description = "Format, mail-server (MX), disposable-provider and role-account checks — never emails anyone."
    category = Category.IDENTITY
    inputs = (InputType.EMAIL,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        email = ctx.target.strip().lower()
        res.node("email", email, label=email)
        m = re.match(r"^([^@\s]+)@([^@\s]+\.[^@\s]+)$", email)
        if not m:
            res.add("Format", "invalid", Confidence.CONFIRMED)
            res.summary = "Not a valid email format"; return res
        local, domain = m.group(1), m.group(2)
        res.add("Format", "valid", Confidence.CONFIRMED)
        res.add("Domain", domain, Confidence.CONFIRMED, pivot=domain)

        # MX records — does the domain actually accept mail?
        has_mx = False
        try:
            import dns.asyncresolver
            resolver = dns.asyncresolver.Resolver(); resolver.lifetime = 6.0
            ans = await resolver.resolve(domain, "MX")
            mxs = sorted((r.preference, r.exchange.to_text().rstrip(".")) for r in ans)
            has_mx = bool(mxs)
            for _, mx in mxs[:3]:
                res.add("Mail server (MX)", mx, Confidence.CONFIRMED)
        except Exception:
            pass
        if not has_mx:
            res.add("Mail server (MX)", "none — domain can't receive mail", Confidence.POSSIBLE)

        # Classifications
        res.add("Provider type",
                "disposable / temporary" if domain in _DISPOSABLE else
                "free webmail" if domain in _FREE else "custom / corporate",
                Confidence.LIKELY if domain in _DISPOSABLE else Confidence.INFO)
        if local in _ROLE:
            res.add("Role account", f"yes ('{local}@') — usually a team, not a person", Confidence.LIKELY)
        # gmail dot/plus normalisation hint (public knowledge)
        if domain == "gmail.com" and ("." in local or "+" in local):
            norm = local.split("+")[0].replace(".", "") + "@gmail.com"
            res.add("Normalises to", norm, Confidence.INFO)

        verdict = ("disposable" if domain in _DISPOSABLE else
                   "deliverable" if has_mx else "no mail server")
        res.summary = f"{email}: valid format · {verdict}"
        return res
