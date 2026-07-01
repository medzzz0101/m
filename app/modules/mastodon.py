"""
modules/mastodon.py
===================
Public profile for a Mastodon account via a fediverse instance's public API (no
auth). Give it user@instance (or a bare handle, which we look up on
mastodon.social). Returns the public display name, bio, follower / following /
toot counts and creation date.

Public profile data only — not identity resolution.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


class MastodonModule(BaseModule):
    key = "mastodon"
    name = "Mastodon (public)"
    category = Category.IDENTITY
    subtitle = "Fediverse public profile"
    accepts = (InputType.USERNAME, InputType.EMAIL)
    needs_network = True
    description = (
        "Public Mastodon/fediverse profile (name, bio, followers, toots, created) "
        "for user@instance or a mastodon.social handle. Public data only."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip().lstrip("@")
        if "@" in v:
            user, instance = v.split("@", 1)
        else:
            user, instance = v, "mastodon.social"
        url = f"https://{instance}/api/v1/accounts/lookup?acct={user}"
        try:
            d = await fetch_json(ctx, url, ttl=3600, namespace="mastodon")
        except Exception as exc:  # noqa: BLE001
            return self.result(
                findings=[{"label": "Mastodon",
                           "summary": f"No public account {user}@{instance}."}],
                confidence=Confidence.INFO, source_url=url)

        bio = re.sub(r"<[^>]+>", "", d.get("note", "") or "").strip()
        findings = [
            {"label": "Account", "summary": f"@{d.get('acct', user)}@{instance}",
             "confidence": "high"},
            {"label": "Display name", "summary": d.get("display_name") or "—"},
            {"label": "Followers", "summary": f"{d.get('followers_count', 0):,}"},
            {"label": "Following", "summary": f"{d.get('following_count', 0):,}"},
            {"label": "Toots", "summary": f"{d.get('statuses_count', 0):,}"},
            {"label": "Created", "summary": (d.get("created_at") or "")[:10]},
        ]
        if bio:
            findings.append({"label": "Bio", "summary": bio[:200]})
        if d.get("url"):
            findings.append({"label": "Profile", "values": [d["url"]]})

        return self.result(
            findings=findings, confidence=Confidence.MEDIUM,
            source_url=d.get("url", url), raw=d,
            nodes=[GraphNode("username", f"{user}@{instance}",
                             label=f"@{user}@{instance}")],
        )
