"""dev_profiles.py — public developer-community profiles via official APIs.

Two more places a person publishes a public identity under a handle:
  * Hacker News — the official Firebase API exposes a user's public karma,
    join date and self-written "about" text.
  * GitLab — the public users API exposes display name, avatar and profile URL.

GUARDRAIL: official public endpoints only, self-published fields only. No
private data, no identity resolution.
"""
from __future__ import annotations

import html
import re

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client


class HackerNewsProfile(BaseModule):
    id = "hackernews_profile"
    name = "Hacker News profile (public)"
    description = "Public Hacker News karma, join date and self-written about text."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@").strip()
        try:
            r = await get_client().get(
                f"https://hacker-news.firebaseio.com/v0/user/{user}.json")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200 or r.json() in (None, "null"):
            res.summary = f"No public Hacker News user '{user}'"; return res
        d = r.json()
        if not isinstance(d, dict):
            res.summary = f"No public Hacker News user '{user}'"; return res
        res.node("username", user, label=f"@{user}")
        res.add("Karma", d.get("karma", 0), Confidence.CONFIRMED,
                link=f"https://news.ycombinator.com/user?id={user}")
        import datetime
        if d.get("created"):
            res.add("Joined", datetime.datetime.utcfromtimestamp(d["created"]).strftime("%Y-%m-%d"),
                    Confidence.CONFIRMED)
        about = html.unescape(re.sub(r"<[^>]+>", " ", d.get("about") or "")).strip()
        if about: res.add("About (public)", re.sub(r"\s+", " ", about)[:220], Confidence.INFO)
        res.add("Submissions", len(d.get("submitted", []) or []), Confidence.INFO)
        res.summary = f"HN @{user}: {d.get('karma',0)} karma"
        return res


class GitLabProfile(BaseModule):
    id = "gitlab_profile"
    name = "GitLab profile (public)"
    description = "Public GitLab display name, avatar and profile link."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@").strip()
        try:
            r = await get_client().get(
                "https://gitlab.com/api/v4/users", params={"username": user})
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        arr = r.json() if r.status_code == 200 else []
        if not isinstance(arr, list) or not arr:
            res.summary = f"No public GitLab user '{user}'"; return res
        d = arr[0]
        node = res.node("username", user, label=f"@{user}")
        if d.get("avatar_url"): node.meta["img"] = d["avatar_url"]
        if d.get("name"): res.add("Name (self-set)", d["name"], Confidence.LIKELY)
        if d.get("web_url"):
            res.add("Profile", d["web_url"], Confidence.CONFIRMED, link=d["web_url"])
        res.add("GitLab ID", d.get("id", "—"), Confidence.INFO)
        res.summary = f"GitLab @{user}: {d.get('name') or 'public profile'}"
        return res
