"""identity.py — YOUR-OWN / authorized exposure checking.

GUARDRAIL: these modules report whether an email appears in PUBLICLY-KNOWN data
breaches by NAME ONLY (e.g. "appears in the 2019 Collection#1 list"). They do
NOT retrieve, display, or store breached passwords, messages, or any third
party's private data. The password tool uses k-anonymity: only the first 5 chars
of a SHA-1 hash ever leave the browser, so the password itself is never sent.
This is the defensive "check my own exposure" use case, nothing more.
"""
from __future__ import annotations

import hashlib

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client


class EmailExposure(BaseModule):
    id = "email_exposure"
    name = "Email breach exposure"
    description = "Which public breaches an email appears in — breach NAMES only, no contents."
    category = Category.IDENTITY
    inputs = (InputType.EMAIL,)
    tier = "base"
    timeout = 20.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        email = ctx.target.strip().lower()
        res.node("email", email, label=email)
        breaches: dict[str, str] = {}   # name -> source

        # Source 1: XposedOrNot (free, no key) — returns a list of breach names.
        try:
            r = await get_client().get(
                f"https://api.xposedornot.com/v1/check-email/{email}")
            if r.status_code == 200:
                d = r.json()
                for b in (d.get("breaches") or [[]])[0] or []:
                    breaches[b] = "XposedOrNot"
        except Exception:
            pass

        # Source 2: LeakCheck public (free, no key) — names + counts, no contents.
        try:
            r = await get_client().get("https://leakcheck.io/api/public",
                                       params={"check": email})
            if r.status_code == 200:
                d = r.json()
                for s in (d.get("sources") or []):
                    nm = s.get("name", "unknown")
                    breaches.setdefault(nm, "LeakCheck")
        except Exception:
            pass

        if not breaches:
            res.summary = "No public breach lists include this email 🎉"
            res.add("Exposure", "not found in public breach lists", Confidence.CONFIRMED)
            return res

        for name, src in sorted(breaches.items()):
            res.add(name, f"listed · {src}", Confidence.LIKELY)
        res.summary = f"Appears in {len(breaches)} public breach list(s)"
        res.extra["breach_count"] = len(breaches)
        # Actionable, defensive guidance — the point of the check.
        res.add("Recommended action", "change reused passwords · enable 2FA", Confidence.INFO)
        return res


class PasswordKAnon(BaseModule):
    id = "password_kanon"
    name = "Password exposure (k-anonymity)"
    description = "Check if a password appears in breaches WITHOUT sending it — client-side hashing."
    category = Category.IDENTITY
    inputs = ()  # handled entirely client-side; listed for the UI, not the runner
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:  # pragma: no cover
        # This module is a UI affordance: the browser hashes the password with
        # SHA-1, sends only the first 5 hex chars to the HIBP range API, and
        # compares suffixes locally. The server never sees the password. See
        # the front-end pw-check overlay. If ever invoked server-side, no-op.
        res = self.result()
        res.summary = "Runs in your browser only — the password never leaves your device."
        return res


class GravatarLookup(BaseModule):
    id = "gravatar"
    name = "Gravatar (public)"
    description = "Whether an email has a public Gravatar avatar/profile (self-published)."
    category = Category.IDENTITY
    inputs = (InputType.EMAIL,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        email = ctx.target.strip().lower()
        h = hashlib.md5(email.encode()).hexdigest()
        try:
            r = await get_client().get(f"https://en.gravatar.com/{h}.json")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "No public Gravatar for this email"; return res
        entry = (r.json().get("entry") or [{}])[0]
        res.node("email", email, label=email)
        res.add("Gravatar profile", entry.get("profileUrl", "—"), Confidence.CONFIRMED,
                link=entry.get("profileUrl"))
        if entry.get("displayName"): res.add("Display name (self-set)", entry["displayName"], Confidence.INFO)
        for acc in entry.get("accounts", [])[:12]:
            res.add(acc.get("shortname", "account"), acc.get("url", ""),
                    Confidence.LIKELY, link=acc.get("url"))
        res.summary = f"Public Gravatar found ({len(entry.get('accounts',[]))} linked accounts)"
        return res


class ExposureScore(BaseModule):
    id = "exposure_score"
    name = "Self-exposure score"
    description = "Aggregates public-footprint signals into a simple 0–100 exposure score."
    category = Category.IDENTITY
    inputs = (InputType.EMAIL, InputType.USERNAME)
    tier = "premium"
    timeout = 30.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        # A meta-module: it re-uses the presence + breach modules and turns the
        # combined footprint into a single, easy-to-act-on number.
        from .social import UsernamePresence
        res = self.result()
        score = 0
        parts: list[str] = []

        pres = await UsernamePresence().run(ctx)
        found = pres.extra.get("found", 0)
        score += min(found * 4, 40)
        parts.append(f"{found} public profiles")
        res.add("Public profiles", f"{found} platforms", Confidence.LIKELY)

        if ctx.input_type == InputType.EMAIL:
            eb = await EmailExposure().run(ctx)
            bc = eb.extra.get("breach_count", 0)
            score += min(bc * 8, 45)
            parts.append(f"{bc} breach lists")
            res.add("Breach lists", f"{bc} public breaches", Confidence.LIKELY)

        score = min(score, 100)
        band = "low" if score < 30 else "moderate" if score < 60 else "high"
        res.add("Exposure score", f"{score}/100 ({band})",
                Confidence.CONFIRMED if band == "low" else Confidence.POSSIBLE)
        res.summary = f"Exposure {score}/100 ({band}) — " + ", ".join(parts)
        res.extra["score"] = score
        return res
