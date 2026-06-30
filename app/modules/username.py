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
    {"name": "GitHub",        "url": "https://github.com/{}",                 "method": "status"},
    {"name": "GitLab",        "url": "https://gitlab.com/{}",                 "method": "status"},
    {"name": "Reddit",        "url": "https://www.reddit.com/user/{}/about.json", "method": "status"},
    {"name": "Twitter/X",     "url": "https://x.com/{}",                      "method": "string_match", "absent": "This account doesn’t exist", "unreliable": True},
    {"name": "Instagram",     "url": "https://www.instagram.com/{}/",         "method": "status", "unreliable": True},
    {"name": "TikTok",        "url": "https://www.tiktok.com/@{}",            "method": "string_match", "absent": "Couldn't find this account"},
    {"name": "Telegram",      "url": "https://t.me/{}",                       "method": "string_match", "absent": "tgme_page_additional"},
    {"name": "Keybase",       "url": "https://keybase.io/{}",                 "method": "status"},
    {"name": "Medium",        "url": "https://medium.com/@{}",               "method": "status"},
    {"name": "Dev.to",        "url": "https://dev.to/{}",                     "method": "status"},
    {"name": "Pastebin",      "url": "https://pastebin.com/u/{}",            "method": "status"},
    {"name": "HackerNews",    "url": "https://news.ycombinator.com/user?id={}", "method": "string_match", "absent": "No such user."},
    {"name": "Steam",         "url": "https://steamcommunity.com/id/{}",      "method": "string_match", "absent": "The specified profile could not be found"},
    {"name": "Twitch",        "url": "https://www.twitch.tv/{}",             "method": "status", "unreliable": True},
    {"name": "Patreon",       "url": "https://www.patreon.com/{}",           "method": "status"},
    {"name": "Behance",       "url": "https://www.behance.net/{}",           "method": "status"},
    {"name": "Dribbble",      "url": "https://dribbble.com/{}",              "method": "status"},
    {"name": "SoundCloud",    "url": "https://soundcloud.com/{}",            "method": "status"},
    {"name": "Vimeo",         "url": "https://vimeo.com/{}",                 "method": "status"},
    {"name": "Flickr",        "url": "https://www.flickr.com/people/{}",     "method": "status"},
    {"name": "About.me",      "url": "https://about.me/{}",                  "method": "status"},
    {"name": "Replit",        "url": "https://replit.com/@{}",              "method": "status"},
    {"name": "PyPI",          "url": "https://pypi.org/user/{}/",           "method": "status"},
    {"name": "npm",           "url": "https://www.npmjs.com/~{}",           "method": "status"},
    {"name": "Mastodon(.social)", "url": "https://mastodon.social/@{}",     "method": "status"},
]


class UsernameModule(BaseModule):
    key = "username"
    name = "Username presence"
    category = Category.IDENTITY
    subtitle = "Is the handle taken? (~25 sites)"
    accepts = (InputType.USERNAME,)
    needs_network = True
    description = (
        "Checks whether a handle is REGISTERED across ~25 public platforms "
        "using per-site status-code OR not-found-string logic. Presence only — "
        "an existing handle is NOT proof of identity and is flagged low-confidence."
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
