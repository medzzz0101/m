"""more_profiles.py — more self-published public identities via official APIs.

  * Lobsters — the .json profile exposes karma, about, and the GitHub / Twitter
    handles the user LINKED THEMSELVES (legal account correlation → traceable).
  * Gravatar — the public profile a person attached to their email hash: display
    name, location, avatar and the accounts they VERIFIED as their own.

GUARDRAIL: official public endpoints; self-published / self-verified fields only.
Gravatar reads only the PUBLIC profile a person chose to publish for that email —
it never reveals a private, unpublished identity.
"""
from __future__ import annotations

import hashlib
import html
import re

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client


class LobstersProfile(BaseModule):
    id = "lobsters_profile"
    name = "Lobsters profile (public)"
    description = "Public Lobsters karma, about, and self-linked GitHub / Twitter handles."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@").strip()
        try:
            r = await get_client().get(f"https://lobste.rs/~{user}.json")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = f"No public Lobsters user '{user}'"; return res
        try:
            d = r.json()
        except Exception:
            res.summary = f"No public Lobsters user '{user}'"; return res
        node = res.node("username", user, label=f"@{user}")
        res.add("Karma", d.get("karma", 0), Confidence.CONFIRMED,
                link=f"https://lobste.rs/~{user}")
        res.add("Joined", (d.get("created_at") or "")[:10], Confidence.CONFIRMED)
        about = html.unescape(re.sub(r"<[^>]+>", " ", d.get("about") or "")).strip()
        if about: res.add("About (public)", re.sub(r"\s+", " ", about)[:220], Confidence.INFO)
        gh = d.get("github_username")
        if gh:
            res.add("GitHub (self-linked)", f"@{gh}", Confidence.CONFIRMED,
                    link=f"https://github.com/{gh}", pivot=gh)
            gn = res.node("username", gh, label=f"@{gh}"); res.edge(node.id, gn.id, "same_as")
        tw = d.get("twitter_username")
        if tw:
            res.add("Twitter (self-linked)", f"@{tw}", Confidence.CONFIRMED,
                    link=f"https://twitter.com/{tw}", pivot=tw)
        res.summary = f"Lobsters @{user}: {d.get('karma',0)} karma"
        return res


class GravatarProfile(BaseModule):
    id = "gravatar_profile"
    name = "Gravatar profile (public)"
    description = "Public Gravatar profile for an email: name, avatar and self-verified accounts."
    category = Category.IDENTITY
    inputs = (InputType.EMAIL,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        email = ctx.target.strip().lower()
        h = hashlib.md5(email.encode()).hexdigest()
        try:
            r = await get_client().get(f"https://en.gravatar.com/{h}.json",
                                       headers={"User-Agent": "limbo-osint"})
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "No public Gravatar profile for this email"; return res
        try:
            entry = (r.json().get("entry") or [None])[0]
        except Exception:
            entry = None
        if not entry:
            res.summary = "No public Gravatar profile for this email"; return res

        node = res.node("email", email, label=email)
        if entry.get("thumbnailUrl"): node.meta["img"] = entry["thumbnailUrl"]
        name = (entry.get("displayName")
                or (entry.get("name") or {}).get("formatted") or "")
        if name:
            res.add("Name (self-published)", name, Confidence.LIKELY)
            pn = res.node("username", name, label=name); res.edge(node.id, pn.id, "same_as")
        if entry.get("currentLocation"):
            res.add("Location (self-set)", entry["currentLocation"], Confidence.INFO)
        about = (entry.get("aboutMe") or "").strip()
        if about: res.add("About (public)", about[:220], Confidence.INFO)
        for acc in (entry.get("accounts") or []):
            label = acc.get("shortname") or acc.get("name") or acc.get("domain") or "account"
            handle = acc.get("username") or acc.get("display") or ""
            verified = "verified" if acc.get("verified") in (True, "true") else "self-listed"
            res.add(f"{label} ({verified})", handle or acc.get("url", "—"),
                    Confidence.CONFIRMED if verified == "verified" else Confidence.LIKELY,
                    link=acc.get("url"), pivot=handle or None)
        res.summary = f"Public Gravatar profile for {email}"
        return res
