"""
modules/discord.py
==================
Resolve a PUBLIC Discord invite to the public information Discord exposes about
the server (guild): name, description, approximate member/online counts, boost
level, verification level and enabled features.

Scope: a Discord invite is a PUBLIC link to a community, and this uses Discord's
own public invite API (no token). It describes the SERVER/community — not its
members, and it does not identify any private individual.
Give it an invite code or a discord.gg / discord.com/invite URL.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json

CODE_RE = re.compile(r"(?:discord(?:\.gg|(?:app)?\.com/invite)/)?([A-Za-z0-9\-]{2,32})")
VERIF = {0: "None", 1: "Low", 2: "Medium", 3: "High", 4: "Highest"}


class DiscordModule(BaseModule):
    key = "discord"
    name = "Discord server (public)"
    category = Category.IDENTITY
    subtitle = "Public invite → server info"
    accepts = (InputType.USERNAME, InputType.URL, InputType.TEXT)
    needs_network = True
    description = (
        "Resolves a PUBLIC Discord invite to the server's public info (name, "
        "member/online counts, boost & verification level, features). Community "
        "data via Discord's public API — not members or individuals."
    )

    async def run(self, value: str, ctx: RunContext):
        m = CODE_RE.search(value.strip())
        if not m:
            return self.result(error="Provide a Discord invite (code or discord.gg URL).")
        code = m.group(1)
        url = (f"https://discord.com/api/v10/invites/{code}"
               "?with_counts=true&with_expiration=true")
        try:
            data = await fetch_json(ctx, url, ttl=1800, namespace="discord",
                                    headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:  # noqa: BLE001
            if "404" in str(exc):
                return self.result(
                    findings=[{"label": "Discord", "summary": f"Invite '{code}' is "
                               "invalid or expired."}],
                    confidence=Confidence.INFO, source_url=f"https://discord.gg/{code}")
            return self.result(error=f"Discord lookup failed: {exc}", source_url=url)

        guild = data.get("guild", {}) or {}
        chan = data.get("channel", {}) or {}
        members = data.get("approximate_member_count")
        online = data.get("approximate_presence_count")
        inviter = data.get("inviter", {}) or {}

        findings = [
            {"label": "Server", "summary": guild.get("name", "—")},
            {"label": "Members (approx)",
             "summary": f"{members:,} total · {online:,} online"
             if members is not None else "—"},
            {"label": "Verification", "summary": VERIF.get(guild.get("verification_level"), "?")},
            {"label": "Boosts", "summary": str(guild.get("premium_subscription_count", 0))},
        ]
        if guild.get("description"):
            findings.append({"label": "Description", "summary": guild["description"][:300]})
        if chan.get("name"):
            findings.append({"label": "Invite channel", "summary": "#" + chan["name"]})
        if guild.get("features"):
            findings.append({"label": "Features", "values": guild["features"][:20]})
        # The invite CREATOR's handle is public on the invite; we surface it as a
        # presence signal only (a handle, not an identity).
        if inviter.get("username"):
            findings.append({"label": "Invite created by (handle)",
                             "summary": "@" + inviter["username"],
                             "confidence": "low"})

        nodes = [GraphNode("service", f"discord:{guild.get('id', code)}",
                           label=guild.get("name", code),
                           props={"members": members, "vanity": code})]
        return self.result(
            findings=findings, confidence=Confidence.HIGH,
            source_url=f"https://discord.gg/{code}",
            raw={"guild": guild, "counts": {"members": members, "online": online}},
            nodes=nodes,
        )
