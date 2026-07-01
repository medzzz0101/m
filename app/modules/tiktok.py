"""
modules/tiktok.py
=================
Public-profile stats for a TikTok handle. TikTok renders public account data
right into the profile page (embedded JSON): display name, bio, verified flag,
follower / following / likes / video counts. This module reads those PUBLIC
numbers — the same ones anyone sees on the profile.

Scope: PUBLIC profile metadata that the account holder publishes for everyone.
It confirms a handle exists and summarises its public stats; it does NOT identify
the private person behind it, link it to other identities, or read anything
non-public.
"""

from __future__ import annotations

import json
import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)

# TikTok embeds a big JSON blob; we pull the fields we need with targeted regex
# to avoid parsing the whole (huge, changing) structure.
FIELDS = {
    "uniqueId": r'"uniqueId":"([^"]+)"',
    "nickname": r'"nickname":"([^"]*)"',
    "signature": r'"signature":"([^"]*)"',
    "verified": r'"verified":(true|false)',
    "followerCount": r'"followerCount":(\d+)',
    "followingCount": r'"followingCount":(\d+)',
    "heartCount": r'"heart(?:Count)?":(\d+)',
    "videoCount": r'"videoCount":(\d+)',
    "privateAccount": r'"privateAccount":(true|false)',
}


def _num(n: str) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return n or "—"


class TikTokModule(BaseModule):
    key = "tiktok"
    name = "TikTok (public profile)"
    category = Category.IDENTITY
    subtitle = "Public follower/like stats"
    accepts = (InputType.USERNAME,)
    needs_network = True
    description = (
        "Reads a TikTok handle's PUBLIC profile stats (display name, bio, verified, "
        "follower/following/likes/video counts). Public profile data only — not "
        "identity resolution."
    )

    async def run(self, value: str, ctx: RunContext):
        handle = value.strip().lstrip("@")
        url = f"https://www.tiktok.com/@{handle}"
        try:
            resp = await ctx.http.get(url, follow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"TikTok fetch failed: {exc}", source_url=url)

        html = resp.text or ""
        vals = {}
        for name, pat in FIELDS.items():
            m = re.search(pat, html)
            if m:
                vals[name] = m.group(1)

        if not vals.get("uniqueId"):
            return self.result(
                findings=[{"label": "TikTok", "summary": f"No public profile found "
                           f"for @{handle} (nonexistent or not accessible)."}],
                confidence=Confidence.INFO, source_url=url)

        bio = (vals.get("signature", "") or "").encode().decode("unicode_escape",
                                                                 "ignore")
        findings = [
            {"label": "Handle", "summary": "@" + vals["uniqueId"],
             "confidence": "high"},
            {"label": "Display name", "summary": vals.get("nickname") or "—"},
            {"label": "Verified", "summary": "yes" if vals.get("verified") == "true"
             else "no"},
            {"label": "Followers", "summary": _num(vals.get("followerCount"))},
            {"label": "Following", "summary": _num(vals.get("followingCount"))},
            {"label": "Likes", "summary": _num(vals.get("heartCount"))},
            {"label": "Videos", "summary": _num(vals.get("videoCount"))},
        ]
        if bio:
            findings.append({"label": "Bio", "summary": bio[:200]})
        if vals.get("privateAccount") == "true":
            findings.append({"label": "Account", "summary": "private"})
        findings.append({"label": "Note",
                         "summary": "Public profile stats only — this is not identity "
                                    "attribution.", "confidence": "info"})

        nodes = [GraphNode("username", handle, label="@" + handle,
                           props={"tiktok_followers": vals.get("followerCount"),
                                  "verified": vals.get("verified")})]
        return self.result(
            findings=findings, confidence=Confidence.MEDIUM, source_url=url,
            raw=vals, nodes=nodes,
        )
