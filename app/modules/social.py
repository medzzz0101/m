"""social.py — public social & messaging OSINT.

GUARDRAIL (read me): every module here checks PUBLIC presence or reads only what
a logged-out visitor can already see (existence of a profile, a public bio, a
public follower count, a public channel's title). NOTHING here deanonymises a
person, resolves a handle to a real identity/phone/address, or scrapes private
data. Username modules answer one question only: "does a public profile with
this name exist on platform X?" — the same thing you'd learn by opening the URL.
"""
from __future__ import annotations

import asyncio
import html
import json
import re

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client


# ---------------------------------------------------------------------------
# The site catalogue for presence checking. Each entry is:
#   name, url template ({u} = username), and how we decide "exists":
#     - "status": HTTP 200 means present, 404 means absent
#     - a string: present only if that string is ABSENT from the body
# Only public, logged-out-viewable profile pages are listed.
# ---------------------------------------------------------------------------
def _mask_email(email: str) -> str:
    """Mask a self-published email: keep 2 chars of the local part + 1 of the
    domain, hide the rest. e.g. jane@gmail.com -> ja••@g•••.com"""
    try:
        local, _, domain = email.partition("@")
        dname, _, tld = domain.rpartition(".")
        ml = local[:2] + "•" * max(len(local) - 2, 2)
        md = (dname[:1] + "•" * max(len(dname) - 1, 2)) if dname else "•••"
        return f"{ml}@{md}.{tld}" if tld else f"{ml}@{md}"
    except Exception:
        return "•••"


SITES: list[dict] = [
    {"n": "GitHub",        "u": "https://github.com/{u}",                  "m": "status", "cat": "dev"},
    {"n": "GitLab",        "u": "https://gitlab.com/{u}",                  "m": "status", "cat": "dev"},
    {"n": "Reddit",        "u": "https://www.reddit.com/user/{u}/about.json","m": "status","cat": "social"},
    {"n": "Instagram",     "u": "https://www.instagram.com/{u}/",          "m": "status", "cat": "social"},
    {"n": "TikTok",        "u": "https://www.tiktok.com/@{u}",             "m": "status", "cat": "social"},
    {"n": "X / Twitter",   "u": "https://nitter.net/{u}",                  "m": "status", "cat": "social"},
    {"n": "Telegram",      "u": "https://t.me/{u}",                        "m": "tgabsent","cat": "chat"},
    {"n": "Threads",       "u": "https://www.threads.net/@{u}",            "m": "status", "cat": "social"},
    {"n": "YouTube",       "u": "https://www.youtube.com/@{u}",            "m": "status", "cat": "social"},
    {"n": "Twitch",        "u": "https://m.twitch.tv/{u}",                 "m": "status", "cat": "social"},
    {"n": "Pinterest",     "u": "https://www.pinterest.com/{u}/",          "m": "status", "cat": "social"},
    {"n": "Steam",         "u": "https://steamcommunity.com/id/{u}",       "m": "steam",  "cat": "gaming"},
    {"n": "Keybase",       "u": "https://keybase.io/{u}",                  "m": "status", "cat": "dev"},
    {"n": "Mastodon (.social)","u": "https://mastodon.social/@{u}",        "m": "status", "cat": "social"},
    {"n": "Bluesky",       "u": "https://bsky.app/profile/{u}.bsky.social","m": "status", "cat": "social"},
    {"n": "Medium",        "u": "https://medium.com/@{u}",                 "m": "status", "cat": "content"},
    {"n": "Dev.to",        "u": "https://dev.to/{u}",                      "m": "status", "cat": "dev"},
    {"n": "Replit",        "u": "https://replit.com/@{u}",                 "m": "status", "cat": "dev"},
    {"n": "SoundCloud",    "u": "https://soundcloud.com/{u}",              "m": "status", "cat": "content"},
    {"n": "Spotify",       "u": "https://open.spotify.com/user/{u}",       "m": "status", "cat": "content"},
    {"n": "Patreon",       "u": "https://www.patreon.com/{u}",             "m": "status", "cat": "content"},
    {"n": "Ko-fi",         "u": "https://ko-fi.com/{u}",                   "m": "status", "cat": "content"},
    {"n": "Behance",       "u": "https://www.behance.net/{u}",             "m": "status", "cat": "content"},
    {"n": "Dribbble",      "u": "https://dribbble.com/{u}",                "m": "status", "cat": "content"},
    {"n": "DeviantArt",    "u": "https://www.deviantart.com/{u}",          "m": "status", "cat": "content"},
    {"n": "Flickr",        "u": "https://www.flickr.com/people/{u}",       "m": "status", "cat": "content"},
    {"n": "VK",            "u": "https://vk.com/{u}",                      "m": "status", "cat": "social"},
    {"n": "Chess.com",     "u": "https://www.chess.com/member/{u}",        "m": "status", "cat": "gaming"},
    {"n": "Lichess",       "u": "https://lichess.org/@/{u}",               "m": "status", "cat": "gaming"},
    {"n": "HackerNews",    "u": "https://news.ycombinator.com/user?id={u}","m": "hn",     "cat": "social"},
    {"n": "Product Hunt",  "u": "https://www.producthunt.com/@{u}",        "m": "status", "cat": "social"},
    {"n": "About.me",      "u": "https://about.me/{u}",                    "m": "status", "cat": "content"},
    {"n": "Linktree",      "u": "https://linktr.ee/{u}",                   "m": "status", "cat": "content"},
    {"n": "Gravatar",      "u": "https://gravatar.com/{u}",                "m": "status", "cat": "social"},
    {"n": "npm",           "u": "https://www.npmjs.com/~{u}",              "m": "status", "cat": "dev"},
    {"n": "PyPI",          "u": "https://pypi.org/user/{u}/",              "m": "status", "cat": "dev"},
    {"n": "Docker Hub",    "u": "https://hub.docker.com/u/{u}",            "m": "status", "cat": "dev"},
    {"n": "CodePen",       "u": "https://codepen.io/{u}",                  "m": "status", "cat": "dev"},
    {"n": "Kaggle",        "u": "https://www.kaggle.com/{u}",              "m": "status", "cat": "dev"},
    {"n": "Wattpad",       "u": "https://www.wattpad.com/user/{u}",        "m": "status", "cat": "content"},
    {"n": "Last.fm",       "u": "https://www.last.fm/user/{u}",            "m": "status", "cat": "content"},
]


class UsernamePresence(BaseModule):
    id = "username_presence"
    name = "Username presence"
    description = "Checks 40+ platforms for a PUBLIC profile with this handle (existence only)."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME, InputType.EMAIL)
    tier = "base"
    timeout = 25.0

    async def _check(self, site: dict, user: str) -> tuple[dict, bool | None]:
        url = site["u"].format(u=user)
        client = get_client()
        try:
            # HEAD-ish: use GET but stream small; some sites reject HEAD.
            r = await client.get(url, timeout=8.0)
        except Exception:
            return site, None  # unknown (network/timeout)
        m = site["m"]
        body_needed = m not in ("status",)
        text = ""
        if body_needed:
            try:
                text = r.text[:6000]
            except Exception:
                text = ""
        if m == "status":
            return site, (r.status_code == 200)
        if m == "tgabsent":
            # t.me returns 200 for everything; a missing channel shows this text.
            return site, ("tgme_page_title" in text or "tgme_page_photo" in text)
        if m == "steam":
            return site, ("error_ctn" not in text and r.status_code == 200)
        if m == "hn":
            return site, ("No such user." not in text and r.status_code == 200)
        return site, (r.status_code == 200)

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@").strip()
        if "@" in user:  # email given — presence check the local part
            user = user.split("@", 1)[0]
        if not user:
            res.ok = False
            res.error = "empty username"
            return res

        # In non-deep mode, sample a strong subset; deep checks everything.
        sites = SITES if ctx.deep else SITES[:22]
        pairs = await asyncio.gather(*(self._check(s, user) for s in sites))

        found = 0
        uname_node = res.node("username", user, label=f"@{user}")
        for site, ok in pairs:
            url = site["u"].format(u=user)
            if ok is True:
                found += 1
                res.add(site["n"], "profile exists", Confidence.LIKELY, link=url, pivot=user)
                pn = res.node("profile", f"{site['n']}:{user}", label=site["n"])
                res.edge(uname_node.id, pn.id, "found_on")
            elif ok is None:
                res.add(site["n"], "unknown (no response)", Confidence.INFO, link=url)
        res.summary = f"Public profile found on {found} of {len(sites)} platforms checked"
        res.extra["found"] = found
        res.extra["checked"] = len(sites)
        return res


class GithubProfile(BaseModule):
    id = "github_profile"
    name = "GitHub profile (public)"
    description = "Public GitHub profile facts: name, bio, repos, followers, join date."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@")
        try:
            r = await get_client().get(f"https://api.github.com/users/{user}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code == 404:
            res.summary = "No public GitHub user with that handle"; return res
        if r.status_code in (403, 429):
            # Shared-host rate limit — not a real failure. Degrade gracefully.
            res.add("GitHub API", "rate-limited on this host — try again shortly",
                    Confidence.INFO, link=f"https://github.com/{user}")
            res.summary = "GitHub API rate-limited (public profile still at the link)"
            return res
        if r.status_code != 200:
            res.ok = False; res.error = f"GitHub API HTTP {r.status_code}"; return res
        d = r.json()
        node = res.node("username", user, label=f"@{user}")
        if d.get("avatar_url"):        # real public avatar → face on the graph/hero
            node.meta["img"] = d["avatar_url"]
        for k, label, conf in [
            ("name", "Name", Confidence.INFO), ("company", "Company", Confidence.INFO),
            ("blog", "Website", Confidence.INFO), ("location", "Location (self-set)", Confidence.INFO),
            ("bio", "Bio", Confidence.INFO), ("public_repos", "Public repos", Confidence.CONFIRMED),
            ("followers", "Followers", Confidence.CONFIRMED), ("created_at", "Joined", Confidence.CONFIRMED),
        ]:
            v = d.get(k)
            if v:
                link = v if k == "blog" and str(v).startswith("http") else None
                res.add(label, v, conf, link=link)
        # Public email — ONLY the address the user chose to publish on their
        # profile (GitHub's public `email` field). Shown MASKED as a courtesy.
        if d.get("email"):
            res.add("Public email (self-published)", _mask_email(d["email"]),
                    Confidence.LIKELY)
        if d.get("blog", "").startswith("http"):
            dn = res.node("url", d["blog"], label="website"); res.edge(node.id, dn.id, "links_to")
        res.summary = f"@{user}: {d.get('public_repos',0)} repos, {d.get('followers',0)} followers"
        return res


class RedditProfile(BaseModule):
    id = "reddit_profile"
    name = "Reddit profile (public)"
    description = "Public Reddit account age and karma from the official about.json."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import datetime as dt
        res = self.result()
        user = ctx.target.lstrip("@")
        try:
            r = await get_client().get(f"https://www.reddit.com/user/{user}/about.json")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "No public Reddit profile"; return res
        d = r.json().get("data", {})
        res.node("username", user, label=f"u/{user}")
        res.add("Link karma", d.get("link_karma", 0), Confidence.CONFIRMED)
        res.add("Comment karma", d.get("comment_karma", 0), Confidence.CONFIRMED)
        if d.get("created_utc"):
            created = dt.datetime.utcfromtimestamp(d["created_utc"]).strftime("%Y-%m-%d")
            res.add("Account created", created, Confidence.CONFIRMED)
        res.add("Verified email", d.get("has_verified_email", "—"), Confidence.INFO)
        res.summary = f"u/{user}: {d.get('total_karma', d.get('link_karma',0))} karma"
        return res


class TelegramChannel(BaseModule):
    id = "telegram_channel"
    name = "Telegram channel (public)"
    description = "Public Telegram channel/group preview: title, subscribers, description."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        name = ctx.target.lstrip("@")
        try:
            r = await get_client().get(f"https://t.me/s/{name}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        html = r.text
        title = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        desc = re.search(r'<meta property="og:description" content="([^"]*)"', html)
        subs = re.search(r'([\d ,\.]+)\s*(?:subscribers|members|подписчик)', html)
        if not title:
            res.summary = "No public Telegram channel preview"; return res
        res.node("username", name, label=f"t.me/{name}")
        res.add("Title", title.group(1), Confidence.CONFIRMED, link=f"https://t.me/{name}")
        if subs: res.add("Subscribers (public)", subs.group(1).strip(), Confidence.LIKELY)
        if desc and desc.group(1): res.add("Description", desc.group(1)[:200], Confidence.INFO)
        res.summary = f"Public channel: {title.group(1)}"
        return res


class DiscordInvite(BaseModule):
    id = "discord_invite"
    name = "Discord invite (public)"
    description = "Resolves a public Discord invite code to server name and member counts."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME, InputType.URL, InputType.TEXT)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        code = ctx.target.rstrip("/").split("/")[-1].lstrip("@")
        try:
            r = await get_client().get(
                f"https://discord.com/api/v10/invites/{code}?with_counts=true")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = "Invalid or expired Discord invite"; return res
        d = r.json(); g = d.get("guild", {})
        res.node("org", g.get("name", code), label="Discord server")
        res.add("Server", g.get("name", "—"), Confidence.CONFIRMED)
        res.add("Members (approx)", d.get("approximate_member_count", "—"), Confidence.LIKELY)
        res.add("Online (approx)", d.get("approximate_presence_count", "—"), Confidence.LIKELY)
        if g.get("description"): res.add("Description", g["description"][:200], Confidence.INFO)
        res.summary = f"Discord: {g.get('name','?')} (~{d.get('approximate_member_count','?')} members)"
        return res


class MastodonProfile(BaseModule):
    id = "mastodon_profile"
    name = "Mastodon profile (public)"
    description = "Public Mastodon account stats via the open ActivityPub API."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        raw = ctx.target.lstrip("@")
        user, _, host = raw.partition("@")
        host = host or "mastodon.social"
        try:
            r = await get_client().get(
                f"https://{host}/api/v1/accounts/lookup?acct={user}")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = f"No public Mastodon account @{user}@{host}"; return res
        d = r.json()
        node = res.node("username", f"{user}@{host}", label=f"@{user}")
        if d.get("avatar"): node.meta["img"] = d["avatar"]
        res.add("Display name", d.get("display_name", "—"), Confidence.CONFIRMED,
                link=d.get("url"))
        bio = html.unescape(re.sub(r"<[^>]+>", "", d.get("note") or "")).strip()
        if bio: res.add("Bio (public)", bio[:220], Confidence.INFO)
        res.add("Followers", d.get("followers_count", 0), Confidence.CONFIRMED)
        res.add("Posts", d.get("statuses_count", 0), Confidence.CONFIRMED)
        res.add("Created", (d.get("created_at") or "")[:10], Confidence.CONFIRMED)
        # recent PUBLIC posts (the account's own public timeline)
        try:
            sr = await get_client().get(
                f"https://{host}/api/v1/accounts/{d['id']}/statuses",
                params={"limit": 5, "exclude_replies": "true", "exclude_reblogs": "true"})
            for st in (sr.json() if sr.status_code == 200 else [])[:5]:
                txt = html.unescape(re.sub(r"<[^>]+>", " ", st.get("content") or "")).strip()
                txt = re.sub(r"\s+", " ", txt)
                if not txt: continue
                when = (st.get("created_at") or "")[:10]
                res.add(f"Post · {when}", txt[:200], Confidence.INFO, link=st.get("url"))
        except Exception:
            pass
        res.summary = f"@{user}@{host}: {d.get('followers_count',0)} followers"
        return res


class BlueskyProfile(BaseModule):
    id = "bluesky_profile"
    name = "Bluesky profile (public)"
    description = "Public Bluesky (AT Protocol) profile: handle, followers, post count."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        h = ctx.target.lstrip("@")
        if "." not in h:
            h = f"{h}.bsky.social"
        try:
            r = await get_client().get(
                "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile",
                params={"actor": h})
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        if r.status_code != 200:
            res.summary = f"No public Bluesky profile for {h}"; return res
        d = r.json()
        node = res.node("username", h, label=f"@{h}")
        if d.get("avatar"): node.meta["img"] = d["avatar"]
        res.add("Display name", d.get("displayName", "—"), Confidence.CONFIRMED,
                link=f"https://bsky.app/profile/{h}")
        bio = (d.get("description") or "").strip()
        if bio: res.add("Bio (public)", bio[:220], Confidence.INFO)
        res.add("Followers", d.get("followersCount", 0), Confidence.CONFIRMED)
        res.add("Following", d.get("followsCount", 0), Confidence.CONFIRMED)
        res.add("Posts", d.get("postsCount", 0), Confidence.CONFIRMED)
        # recent PUBLIC posts from the author's public feed
        try:
            fr = await get_client().get(
                "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
                params={"actor": h, "limit": 8, "filter": "posts_no_replies"})
            feed = fr.json().get("feed", []) if fr.status_code == 200 else []
            shown = 0
            for item in feed:
                post = item.get("post", {})
                if item.get("reason"): continue          # skip reposts
                rec = post.get("record", {})
                txt = re.sub(r"\s+", " ", (rec.get("text") or "")).strip()
                if not txt: continue
                when = (rec.get("createdAt") or "")[:10]
                uri = post.get("uri", "")
                rkey = uri.rsplit("/", 1)[-1] if uri else ""
                link = f"https://bsky.app/profile/{h}/post/{rkey}" if rkey else None
                res.add(f"Post · {when}", txt[:200], Confidence.INFO, link=link)
                shown += 1
                if shown >= 5: break
        except Exception:
            pass
        res.summary = f"@{h}: {d.get('followersCount',0)} followers"
        return res


class SteamProfile(BaseModule):
    id = "steam_profile"
    name = "Steam profile (public)"
    description = "Public Steam community profile: display name, status, real name if shared."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@")
        try:
            r = await get_client().get(f"https://steamcommunity.com/id/{user}?xml=1")
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        html = r.text
        if "<steamID>" not in html:
            res.summary = "No public Steam vanity profile"; return res
        def tag(t):
            m = re.search(rf"<{t}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{t}>", html, re.S)
            return m.group(1).strip() if m else None
        res.node("username", user, label=f"Steam:{user}")
        if tag("steamID"): res.add("Display name", tag("steamID"), Confidence.CONFIRMED)
        if tag("realname"): res.add("Real name (self-shared)", tag("realname"), Confidence.INFO)
        if tag("stateMessage"): res.add("Status", re.sub("<.*?>", " ", tag("stateMessage")), Confidence.INFO)
        if tag("memberSince"): res.add("Member since", tag("memberSince"), Confidence.CONFIRMED)
        if tag("location"): res.add("Location (self-set)", tag("location"), Confidence.INFO)
        res.summary = f"Steam: {tag('steamID') or user}"
        return res


class KeybaseProfile(BaseModule):
    id = "keybase_profile"
    name = "Keybase identities (public)"
    description = "Public cryptographic identity proofs a user has linked on Keybase."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME,)
    tier = "elite"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@")
        try:
            r = await get_client().get(
                "https://keybase.io/_/api/1.0/user/lookup.json",
                params={"usernames": user, "fields": "proofs_summary,profile"})
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        them = (r.json().get("them") or [None])[0] if r.status_code == 200 else None
        if not them:
            res.summary = "No public Keybase user"; return res
        node = res.node("username", user, label=f"Keybase:{user}")
        proofs = (them.get("proofs_summary") or {}).get("all", [])
        for p in proofs:
            svc = p.get("proof_type", "proof"); name = p.get("nametag", "")
            res.add(svc, name, Confidence.CONFIRMED, link=p.get("service_url"))
            pn = res.node("username", f"{svc}:{name}", label=name); res.edge(node.id, pn.id, "same_as")
        res.summary = f"Keybase {user}: {len(proofs)} linked identities"
        return res
