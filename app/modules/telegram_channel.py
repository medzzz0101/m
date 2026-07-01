"""
modules/telegram_channel.py
===========================
Analytics for a PUBLIC Telegram channel via its public web feed (t.me/s/<name>).
Public channels are broadcast media — anyone can open the feed in a browser. We
summarise: subscriber / photo / video / link counts, a sample of recent public
posts, and other @channels this one links to (useful for mapping a network of
public channels).

Scope: PUBLIC broadcast content only. This describes a channel's public output,
not its subscribers, and never identifies a private person.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)

COUNTER_RE = re.compile(
    r'tgme_channel_info_counter[^>]*>\s*<span class="counter_value"[^>]*>([^<]+)</span>\s*'
    r'<span class="counter_type">([^<]+)</span>', re.S)
POST_RE = re.compile(r'tgme_widget_message_text[^>]*>(.*?)</div>', re.S)
MENTION_RE = re.compile(r'>@([A-Za-z0-9_]{4,32})<')


def _strip(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).replace("&nbsp;", " ").strip()


class TelegramChannelModule(BaseModule):
    key = "telegram_channel"
    name = "Telegram channel analytics"
    category = Category.IDENTITY
    subtitle = "Public feed: stats + posts"
    accepts = (InputType.USERNAME,)
    needs_network = True
    description = (
        "Analyses a PUBLIC Telegram channel's web feed: subscriber/photo/video/"
        "link counts, recent post samples and linked @channels. Public broadcast "
        "data only."
    )

    async def run(self, value: str, ctx: RunContext):
        handle = value.strip().lstrip("@")
        url = f"https://t.me/s/{handle}"
        try:
            resp = await ctx.http.get(url, follow_redirects=True,
                                      headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"t.me feed fetch failed: {exc}", source_url=url)

        html = resp.text or ""
        if "tgme_channel_info" not in html and "tgme_widget_message" not in html:
            return self.result(
                findings=[{"label": "Telegram", "summary": f"@{handle} is not a "
                           "public channel (private, a user, or nonexistent)."}],
                confidence=Confidence.INFO, source_url=url)

        counters = {t.strip().lower(): v.strip() for v, t in COUNTER_RE.findall(html)}
        posts_raw = POST_RE.findall(html)
        posts = [_strip(p)[:200] for p in posts_raw if _strip(p)][:5]
        mentions = sorted(set(MENTION_RE.findall(html)) - {handle})[:15]

        findings = [
            {"label": "Channel", "summary": f"t.me/{handle}", "confidence": "high"},
            {"label": "Subscribers", "summary": counters.get("subscribers", "—")},
        ]
        for key in ("photos", "videos", "links", "files"):
            if key in counters:
                findings.append({"label": key.capitalize(), "summary": counters[key]})
        if posts:
            findings.append({"label": "Recent public posts (sample)", "values": posts})
        if mentions:
            findings.append({"label": "Linked @channels",
                             "values": [f"@{m}" for m in mentions]})
        findings.append({"label": "Note",
                         "summary": "Public broadcast content only — not subscribers "
                                    "or any private identity.", "confidence": "info"})

        nodes = [GraphNode("username", handle, label=f"@{handle}",
                           props={"subscribers": counters.get("subscribers")})]
        edges: list[GraphEdge] = []
        for m in mentions:
            nodes.append(GraphNode("username", m, label=f"@{m}"))
            edges.append(GraphEdge(f"username:{handle}", f"username:{m}", "related_to"))

        return self.result(
            findings=findings, confidence=Confidence.MEDIUM, source_url=url,
            raw={"counters": counters, "mentions": mentions, "posts": posts},
            nodes=nodes, edges=edges,
        )
