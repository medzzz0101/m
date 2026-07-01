"""
modules/username.py
===================
"Is this handle TAKEN on these platforms?" — presence only.

IMPORTANT / GUARDRAIL: this module answers ONE narrow question — does an
account with this name exist on a site — and nothing else. It does NOT, and
must NEVER be wired to, link a handle to a real person. A handle existing on
two sites is NOT evidence they are the same human; we surface that caveat
loudly and flag every hit as LOW confidence.

The detection logic (the part the user specifically designed):
each site config uses ONE of two strategies, because a bare HTTP 200 gives
false positives on login-wall sites (Instagram/Twitter return 200 for missing
users):

  * "status"       : the URL returns 404 for a missing user, 200 for a real
                     one. Trust the status code.
  * "string_match" : the site returns 200 either way, so we look for a
                     "not-found marker" string in the body. If that marker is
                     ABSENT, the profile exists.

Both are implemented below. Sites where neither is reliable are marked
unreliable=True and reported as INFO, never as a confident hit.
"""

from __future__ import annotations

import asyncio

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import host_of

# ---------------------------------------------------------------------------
# Platform catalog. ~25 sites. Each entry:
#   url           : {} placeholder filled with the username
#   method        : "status" | "string_match"
#   absent        : (string_match only) marker that appears ONLY on not-found
#                   pages — its ABSENCE means the profile exists
#   unreliable    : True if even this heuristic is shaky (report as INFO)
# ---------------------------------------------------------------------------
SITES: list[dict] = [
    # ---- Dev / tech ----
    {"name": "GitHub",        "url": "https://github.com/{}",                 "method": "status", "cat": "dev"},
    {"name": "GitLab",        "url": "https://gitlab.com/{}",                 "method": "status", "cat": "dev"},
    {"name": "Keybase",       "url": "https://keybase.io/{}",                 "method": "status", "cat": "dev"},
    {"name": "Dev.to",        "url": "https://dev.to/{}",                     "method": "status", "cat": "dev"},
    {"name": "Replit",        "url": "https://replit.com/@{}",               "method": "status", "cat": "dev"},
    {"name": "PyPI",          "url": "https://pypi.org/user/{}/",            "method": "status", "cat": "dev"},
    {"name": "npm",           "url": "https://www.npmjs.com/~{}",            "method": "status", "cat": "dev"},
    {"name": "Docker Hub",    "url": "https://hub.docker.com/u/{}",          "method": "status", "cat": "dev"},
    {"name": "HackerNews",    "url": "https://news.ycombinator.com/user?id={}", "method": "string_match", "absent": "No such user.", "cat": "dev"},
    {"name": "CodePen",       "url": "https://codepen.io/{}",                "method": "status", "cat": "dev"},
    {"name": "Kaggle",        "url": "https://www.kaggle.com/{}",            "method": "status", "cat": "dev"},
    {"name": "Hackerone",     "url": "https://hackerone.com/{}",             "method": "status", "cat": "dev"},
    {"name": "Bitbucket",     "url": "https://bitbucket.org/{}/",            "method": "status", "cat": "dev"},
    # ---- Social ----
    {"name": "Twitter/X",     "url": "https://nitter.net/{}",                "method": "string_match", "absent": "User not found", "cat": "social", "unreliable": True},
    {"name": "Instagram",     "url": "https://www.instagram.com/{}/",         "method": "status", "cat": "social", "unreliable": True},
    {"name": "TikTok",        "url": "https://www.tiktok.com/@{}",           "method": "string_match", "absent": "Couldn't find this account", "cat": "social"},
    {"name": "Telegram",      "url": "https://t.me/{}",                      "method": "string_match", "absent": "tgme_page_additional", "cat": "social"},
    {"name": "Facebook",      "url": "https://www.facebook.com/{}",          "method": "status", "cat": "social", "unreliable": True},
    {"name": "Threads",       "url": "https://www.threads.net/@{}",          "method": "status", "cat": "social", "unreliable": True},
    {"name": "Snapchat",      "url": "https://www.snapchat.com/add/{}",      "method": "string_match", "absent": "Sorry! We couldn", "cat": "social"},
    {"name": "Reddit",        "url": "https://www.reddit.com/user/{}/about.json", "method": "status", "cat": "social"},
    {"name": "Mastodon",      "url": "https://mastodon.social/@{}",          "method": "status", "cat": "social"},
    {"name": "Bluesky",       "url": "https://bsky.app/profile/{}.bsky.social", "method": "status", "cat": "social", "unreliable": True},
    {"name": "VK",            "url": "https://vk.com/{}",                    "method": "string_match", "absent": "page is not found", "cat": "social"},
    {"name": "Linktree",      "url": "https://linktr.ee/{}",                 "method": "string_match", "absent": "the page you", "cat": "social"},
    {"name": "About.me",      "url": "https://about.me/{}",                  "method": "status", "cat": "social"},
    {"name": "Gravatar",      "url": "https://gravatar.com/{}",              "method": "status", "cat": "social"},
    # ---- Media / creative ----
    {"name": "YouTube",       "url": "https://www.youtube.com/@{}",          "method": "string_match", "absent": "This page isn", "cat": "media"},
    {"name": "Twitch",        "url": "https://m.twitch.tv/{}",               "method": "string_match", "absent": "Sorry. Unless you", "cat": "media", "unreliable": True},
    {"name": "SoundCloud",    "url": "https://soundcloud.com/{}",            "method": "status", "cat": "media"},
    {"name": "Vimeo",         "url": "https://vimeo.com/{}",                 "method": "status", "cat": "media"},
    {"name": "Flickr",        "url": "https://www.flickr.com/people/{}",     "method": "status", "cat": "media"},
    {"name": "Behance",       "url": "https://www.behance.net/{}",           "method": "status", "cat": "media"},
    {"name": "Dribbble",      "url": "https://dribbble.com/{}",              "method": "status", "cat": "media"},
    {"name": "DeviantArt",    "url": "https://www.deviantart.com/{}",        "method": "status", "cat": "media"},
    {"name": "Spotify",       "url": "https://open.spotify.com/user/{}",     "method": "status", "cat": "media"},
    {"name": "Bandcamp",      "url": "https://bandcamp.com/{}",              "method": "status", "cat": "media"},
    {"name": "Patreon",       "url": "https://www.patreon.com/{}",           "method": "status", "cat": "media"},
    {"name": "Medium",        "url": "https://medium.com/@{}",              "method": "status", "cat": "media"},
    {"name": "Pinterest",     "url": "https://www.pinterest.com/{}/",        "method": "status", "cat": "media", "unreliable": True},
    # ---- Gaming / community ----
    {"name": "Steam",         "url": "https://steamcommunity.com/id/{}",     "method": "string_match", "absent": "The specified profile could not be found", "cat": "gaming"},
    {"name": "Chess.com",     "url": "https://www.chess.com/member/{}",      "method": "status", "cat": "gaming"},
    {"name": "Lichess",       "url": "https://lichess.org/@/{}",             "method": "status", "cat": "gaming"},
    {"name": "Roblox",        "url": "https://www.roblox.com/user.aspx?username={}", "method": "string_match", "absent": "Page cannot be found", "cat": "gaming"},
    {"name": "Xbox Gamertag", "url": "https://xboxgamertag.com/search/{}",   "method": "string_match", "absent": "No user found", "cat": "gaming"},
    # ---- Shops / misc ----
    {"name": "Pastebin",      "url": "https://pastebin.com/u/{}",            "method": "status", "cat": "misc"},
    {"name": "Ko-fi",         "url": "https://ko-fi.com/{}",                 "method": "status", "cat": "misc"},
    {"name": "BuyMeACoffee",  "url": "https://www.buymeacoffee.com/{}",      "method": "status", "cat": "misc"},
    {"name": "Product Hunt",  "url": "https://www.producthunt.com/@{}",      "method": "status", "cat": "misc"},
    {"name": "Trello",        "url": "https://trello.com/{}",                "method": "status", "cat": "misc", "unreliable": True},
    {"name": "Wattpad",       "url": "https://www.wattpad.com/user/{}",      "method": "status", "cat": "misc"},
]


class UsernameModule(BaseModule):
    key = "username"
    name = "Username presence"
    category = Category.IDENTITY
    subtitle = "Handle across ~50 platforms"
    accepts = (InputType.USERNAME,)
    needs_network = True
    description = (
        "Checks whether a handle is REGISTERED across ~50 public platforms "
        "(social, dev, media, gaming) using per-site status-code OR "
        "not-found-string logic. Presence only — an existing handle is NOT proof "
        "of identity and is flagged low-confidence."
    )

    async def _check(self, site: dict, username: str, ctx: RunContext) -> dict:
        url = site["url"].format(username)
        limiter = ctx.extra.get("rate_limiter")
        host = host_of(url)
        try:
            async def _do():
                # follow_redirects: many sites 301 -> canonical profile URL.
                return await ctx.http.get(
                    url, follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (OSINT-presence-check)"},
                )
            if limiter is not None:
                async with limiter.slot(host):
                    resp = await _do()
            else:
                resp = await _do()
        except Exception as exc:  # noqa: BLE001
            return {"site": site["name"], "url": url, "exists": None,
                    "note": f"error: {type(exc).__name__}"}

        exists: bool | None
        if site["method"] == "status":
            exists = resp.status_code == 200
        else:  # string_match
            marker = site.get("absent", "")
            if resp.status_code != 200:
                exists = resp.status_code in (301, 302)  # some redirect to real
            else:
                # Profile exists when the not-found marker is ABSENT.
                exists = marker.lower() not in resp.text.lower()

        return {
            "site": site["name"],
            "url": url,
            "exists": exists,
            "status": resp.status_code,
            "method": site["method"],
            "unreliable": site.get("unreliable", False),
        }

    async def run(self, value: str, ctx: RunContext):
        username = value.strip().lstrip("@")

        # Check all sites concurrently.
        checks = await asyncio.gather(
            *(self._check(s, username, ctx) for s in SITES)
        )

        hits = [c for c in checks if c["exists"] is True and not c["unreliable"]]
        weak = [c for c in checks if c["exists"] is True and c["unreliable"]]

        findings = [{
            "label": "Caveat",
            "summary": "A handle existing on a site is NOT proof of identity. "
                       "Treat every hit as a lead, never as attribution.",
            "confidence": "info",
        }, {
            "label": "Found on",
            "summary": f"{len(hits)} reliable + {len(weak)} login-walled",
            "values": [f"{c['site']} — {c['url']}" for c in hits],
        }]
        if weak:
            findings.append({
                "label": "Low-confidence (login-wall sites)",
                "values": [f"{c['site']} — {c['url']}" for c in weak],
                "confidence": "low",
            })

        # Graph: the username node + a 'taken on' marker per reliable hit.
        nodes = [GraphNode("username", username)]
        for c in hits:
            nodes.append(GraphNode("service", c["site"], label=c["site"]))

        return self.result(
            findings=findings,
            # Presence is inherently low-confidence as an *identity* signal.
            confidence=Confidence.LOW if hits else Confidence.INFO,
            raw={"checks": checks},
            nodes=nodes,
        )
