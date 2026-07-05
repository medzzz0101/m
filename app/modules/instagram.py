"""instagram.py — public Instagram profile facts.

Reads the SAME public profile a logged-out visitor sees on instagram.com:
display name, bio, follower/following/post counts, whether the account is
private, the external link and the public profile picture. Uses Instagram's
public web_profile_info endpoint (the one the profile page itself calls).

Instagram aggressively rate-limits datacenter IPs, so this degrades
gracefully: even when the API is blocked it still surfaces the public profile
link and the public avatar, so the face and the link always appear.

GUARDRAIL: public profile fields only. If the account is private, only the
public header (name, counts, avatar) is shown — never private posts/content.
"""
from __future__ import annotations

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client

_IG_APP_ID = "936619743392459"
_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
       "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram")


class InstagramProfile(BaseModule):
    id = "instagram_profile"
    name = "Instagram profile (public)"
    description = "Public Instagram name, bio, followers, posts, privacy and avatar."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@").strip().rstrip("/")
        if "/" in user:
            user = user.rsplit("/", 1)[-1]
        link = f"https://www.instagram.com/{user}/"
        node = res.node("username", user, label=f"@{user}")
        # unavatar resolves the public IG picture reliably from the browser,
        # so the face shows even when Instagram blocks the server-side API.
        node.meta["img"] = f"https://unavatar.io/instagram/{user}?fallback=false"

        try:
            r = await get_client().get(
                "https://i.instagram.com/api/v1/users/web_profile_info/",
                params={"username": user},
                headers={"X-IG-App-ID": _IG_APP_ID, "User-Agent": _UA},
                timeout=10.0)
        except Exception:
            r = None

        d = None
        if r is not None and r.status_code == 200:
            try:
                d = (r.json().get("data") or {}).get("user")
            except Exception:
                d = None

        if not d:
            # blocked / rate-limited / not found — still give the link + face
            res.add("Profile", link, Confidence.INFO, link=link, pivot=user)
            res.add("Public API", "rate-limited from server — open the profile link",
                    Confidence.INFO)
            res.summary = f"Instagram @{user}: public profile link (API rate-limited)"
            return res

        if d.get("profile_pic_url_hd") or d.get("profile_pic_url"):
            pass  # keep unavatar (IG CDN hotlink-protects), data below is what matters
        if d.get("full_name"):
            res.add("Name (self-set)", d["full_name"], Confidence.LIKELY)
        priv = d.get("is_private")
        res.add("Account", "private" if priv else "public", Confidence.CONFIRMED, link=link)
        if d.get("is_verified"):
            res.add("Verified", "yes (blue check)", Confidence.CONFIRMED)
        bio = (d.get("biography") or "").strip()
        if bio:
            res.add("Bio (public)", bio[:220], Confidence.INFO)
        ext = d.get("external_url")
        if ext:
            res.add("Link", ext, Confidence.LIKELY, link=ext)
            un = res.node("url", ext, label="link"); res.edge(node.id, un.id, "links_to")
        res.add("Followers", (d.get("edge_followed_by") or {}).get("count", 0), Confidence.CONFIRMED)
        res.add("Following", (d.get("edge_follow") or {}).get("count", 0), Confidence.CONFIRMED)
        res.add("Posts", (d.get("edge_owner_to_timeline_media") or {}).get("count", 0),
                Confidence.CONFIRMED)
        res.add("Profile", link, Confidence.INFO, link=link, pivot=user)
        res.summary = (f"Instagram @{user}: "
                       f"{(d.get('edge_followed_by') or {}).get('count', 0)} followers"
                       + (" · private" if priv else ""))
        return res
