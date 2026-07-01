"""
modules/bluesky.py
==================
Public profile stats for a Bluesky handle via the public AT-Protocol API (no
auth). Bluesky is an open, public social network; its app-view API serves the
same public profile data anyone sees: display name, description, follower /
following / post counts and the account's DID.

Public profile data only — not identity resolution.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


class BlueskyModule(BaseModule):
    key = "bluesky"
    name = "Bluesky (public)"
    category = Category.IDENTITY
    subtitle = "Public profile stats"
    accepts = (InputType.USERNAME,)
    needs_network = True
    description = (
        "Reads a Bluesky handle's PUBLIC profile (display name, bio, follower/"
        "following/post counts, DID) via the open AT-Protocol API. Public data only."
    )

    async def run(self, value: str, ctx: RunContext):
        handle = value.strip().lstrip("@")
        # Bare names default to the bsky.social domain.
        if "." not in handle:
            handle = f"{handle}.bsky.social"
        url = ("https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"
               f"?actor={handle}")
        try:
            d = await fetch_json(ctx, url, ttl=3600, namespace="bsky")
        except Exception as exc:  # noqa: BLE001
            if "400" in str(exc):
                return self.result(
                    findings=[{"label": "Bluesky", "summary": f"No profile for @{handle}."}],
                    confidence=Confidence.INFO, source_url=url)
            return self.result(error=f"Bluesky lookup failed: {exc}", source_url=url)

        findings = [
            {"label": "Handle", "summary": "@" + d.get("handle", handle),
             "confidence": "high"},
            {"label": "Display name", "summary": d.get("displayName") or "—"},
            {"label": "Followers", "summary": f"{d.get('followersCount', 0):,}"},
            {"label": "Following", "summary": f"{d.get('followsCount', 0):,}"},
            {"label": "Posts", "summary": f"{d.get('postsCount', 0):,}"},
        ]
        if d.get("description"):
            findings.append({"label": "Bio", "summary": d["description"][:200]})
        if d.get("did"):
            findings.append({"label": "DID", "summary": d["did"]})

        return self.result(
            findings=findings, confidence=Confidence.MEDIUM,
            source_url=f"https://bsky.app/profile/{d.get('handle', handle)}",
            raw=d,
            nodes=[GraphNode("username", handle, label="@" + handle,
                             props={"bsky_followers": d.get("followersCount")})],
        )
