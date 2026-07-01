"""
modules/steam.py
================
Public Steam community profile for a vanity handle via Steam's public XML profile
endpoint (steamcommunity.com/id/<name>?xml=1, no key). It returns the public
fields a Steam user exposes: persona name, SteamID64, account age, online state,
avatar, and (if the user made them public) their real-name field, location and
group memberships.

Scope: PUBLIC profile data the account chose to publish. It confirms a handle and
summarises public gaming-profile info; it is not identity resolution.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_text

TAGS = ["steamID64", "steamID", "onlineState", "stateMessage", "memberSince",
        "location", "realname", "vacBanned"]


class SteamModule(BaseModule):
    key = "steam"
    name = "Steam (public profile)"
    category = Category.IDENTITY
    subtitle = "Public community profile"
    accepts = (InputType.USERNAME,)
    needs_network = True
    description = (
        "Reads a Steam vanity handle's PUBLIC community profile (persona, "
        "SteamID64, member-since, online state, and public real-name/location if "
        "the user published them). Public profile data only."
    )

    async def run(self, value: str, ctx: RunContext):
        handle = value.strip().lstrip("@")
        url = f"https://steamcommunity.com/id/{handle}?xml=1"
        try:
            xml = await fetch_text(ctx, url, ttl=3600, namespace="steam",
                                   headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Steam fetch failed: {exc}", source_url=url)

        if "<steamID64>" not in xml:
            return self.result(
                findings=[{"label": "Steam", "summary": f"No public profile for "
                           f"'{handle}' (custom URL not set or private)."}],
                confidence=Confidence.INFO, source_url=f"https://steamcommunity.com/id/{handle}")

        vals = {}
        for tag in TAGS:
            m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", xml, re.S)
            if m and m.group(1).strip():
                vals[tag] = m.group(1).strip()

        sid = vals.get("steamID64", "")
        findings = [
            {"label": "Persona", "summary": vals.get("steamID", handle),
             "confidence": "high"},
            {"label": "SteamID64", "summary": sid},
            {"label": "Member since", "summary": vals.get("memberSince", "—")},
            {"label": "Status", "summary": vals.get("stateMessage")
             or vals.get("onlineState", "—")},
        ]
        if vals.get("realname"):
            findings.append({"label": "Real name (public)", "summary": vals["realname"],
                             "confidence": "low"})
        if vals.get("location"):
            findings.append({"label": "Location (public)", "summary": vals["location"]})
        if vals.get("vacBanned") is not None:
            findings.append({"label": "VAC banned",
                             "summary": "yes" if vals.get("vacBanned") == "1" else "no"})
        if sid:
            findings.append({"label": "Links",
                             "values": [f"https://steamcommunity.com/profiles/{sid}",
                                        f"https://steamid.io/lookup/{sid}"]})
        findings.append({"label": "Note",
                         "summary": "Public profile fields only (incl. any real-name "
                                    "the user chose to publish).", "confidence": "info"})

        nodes = [GraphNode("username", handle, label=handle,
                           props={"steamid64": sid})]
        return self.result(
            findings=findings, confidence=Confidence.MEDIUM, source_url=url,
            raw=vals, nodes=nodes,
        )
