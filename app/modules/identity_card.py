"""identity_card.py — a consolidated PUBLIC identity summary for a username.

Aggregates, into one clean card, the things a person PUBLISHED THEMSELVES:
  * GitHub public profile — display name, company, location (self-set), website,
    linked Twitter, and the public email GitHub exposes (shown MASKED)
  * Keybase — the other accounts the person cryptographically CLAIMS as theirs

This is legal identity correlation: it links public accounts a person declared
as their own. It never uses breach data, never resolves a phone, and never
reveals a private, non-published identity/address.
"""
from __future__ import annotations

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client
from .social import _mask_email


class IdentityCard(BaseModule):
    id = "identity_card"
    name = "Public identity card"
    description = "One card: self-published name, masked public email, website & self-claimed linked accounts."
    category = Category.IDENTITY
    inputs = (InputType.USERNAME,)
    tier = "base"
    timeout = 18.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@").strip()
        node = res.node("username", user, label=f"@{user}")
        found_any = False

        # --- GitHub public profile (self-published fields only) ---
        try:
            r = await get_client().get(f"https://api.github.com/users/{user}")
            if r.status_code == 200:
                d = r.json()
                found_any = True
                if d.get("avatar_url"):        # public profile picture → face on the graph
                    node.meta["img"] = d["avatar_url"]
                if d.get("name"): res.add("Name (self-set)", d["name"], Confidence.LIKELY)
                if d.get("company"): res.add("Company (self-set)", d["company"], Confidence.INFO)
                if d.get("location"): res.add("Location (self-set)", d["location"], Confidence.INFO)
                if d.get("email"): res.add("Public email (masked)", _mask_email(d["email"]), Confidence.LIKELY)
                if d.get("blog", "").startswith("http"):
                    res.add("Website", d["blog"], Confidence.LIKELY, link=d["blog"])
                    wn = res.node("url", d["blog"], label="website"); res.edge(node.id, wn.id, "links_to")
                if d.get("twitter_username"):
                    tw = d["twitter_username"]
                    res.add("Twitter (self-declared)", f"@{tw}", Confidence.LIKELY,
                            link=f"https://twitter.com/{tw}", pivot=tw)
                    tn = res.node("username", tw, label=f"@{tw}"); res.edge(node.id, tn.id, "same_as")
        except Exception:
            pass

        # --- Keybase self-claimed identities (cryptographic proofs) ---
        try:
            r = await get_client().get(
                "https://keybase.io/_/api/1.0/user/lookup.json",
                params={"usernames": user, "fields": "proofs_summary"})
            them = (r.json().get("them") or [None])[0] if r.status_code == 200 else None
            if them:
                found_any = True
                proofs = (them.get("proofs_summary") or {}).get("all", [])
                for p in proofs:
                    svc = p.get("proof_type", "account"); name = p.get("nametag", "")
                    res.add(f"Linked: {svc} (self-claimed)", name, Confidence.CONFIRMED,
                            link=p.get("service_url"), pivot=name)
                    pn = res.node("username", f"{svc}:{name}", label=name)
                    res.edge(node.id, pn.id, "same_as")
        except Exception:
            pass

        res.add("Scope", "self-published & self-claimed public data only", Confidence.INFO)
        if not found_any:
            res.summary = f"No self-published public identity data for @{user}"
        else:
            res.summary = f"Public identity card for @{user} — self-declared links"
        return res
