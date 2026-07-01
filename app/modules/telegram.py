"""
modules/telegram.py
===================
Resolve a PUBLIC Telegram handle (t.me/<name>) to whatever Telegram itself
publishes on the public preview page: the title, the description, and — for
public CHANNELS — the subscriber count and latest-post hints.

Scope: this reads the PUBLIC broadcast page anyone can open in a browser. A
public channel is a broadcast medium, not a private person. We do NOT attempt to
identify who runs it, read members, or access anything non-public. If the handle
is a private user with no public page, we simply report "no public page".
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import host_of

TITLE_RE = re.compile(r'tgme_page_title["\'][^>]*>\s*<[^>]*>?([^<]+)', re.S)
DESC_RE = re.compile(r'tgme_page_description["\'][^>]*>(.*?)</div>', re.S)
EXTRA_RE = re.compile(r'tgme_page_extra["\'][^>]*>([^<]+)', re.S)


def _clean(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


class TelegramModule(BaseModule):
    key = "telegram"
    name = "Telegram (public)"
    category = Category.IDENTITY
    subtitle = "Public channel / handle preview"
    accepts = (InputType.USERNAME,)
    needs_network = True
    description = (
        "Reads Telegram's PUBLIC t.me preview for a handle: title, description "
        "and — for public channels — subscriber count. Public broadcast data only."
    )

    async def run(self, value: str, ctx: RunContext):
        handle = value.strip().lstrip("@")
        url = f"https://t.me/{handle}"
        try:
            resp = await ctx.http.get(url, follow_redirects=True,
                                      headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"t.me fetch failed: {exc}", source_url=url)

        html = resp.text or ""
        # A real public page carries tgme_page_title; missing/private -> not present.
        if "tgme_page_title" not in html:
            return self.result(
                findings=[{"label": "Telegram",
                           "summary": f"No public page for @{handle} "
                                      "(private user, doesn't exist, or no public channel).",
                           "confidence": "info"}],
                confidence=Confidence.INFO, source_url=url)

        title = _clean((TITLE_RE.search(html) or [None, ""])[1]) if TITLE_RE.search(html) else ""
        desc = _clean((DESC_RE.search(html) or [None, ""])[1]) if DESC_RE.search(html) else ""
        extra = _clean((EXTRA_RE.search(html) or [None, ""])[1]) if EXTRA_RE.search(html) else ""

        findings = [
            {"label": "Public page", "summary": f"t.me/{handle} exists",
             "confidence": "high"},
            {"label": "Title", "summary": title or "—"},
        ]
        if extra:  # e.g. "10 217 035 subscribers" for a channel
            findings.append({"label": "Stats", "summary": extra})
        if desc:
            findings.append({"label": "Description", "summary": desc[:300]})
        findings.append({"label": "Note",
                         "summary": "Public broadcast data only — this does not "
                                    "identify who operates the handle.",
                         "confidence": "info"})

        nodes = [GraphNode("username", handle, label=f"@{handle}",
                           props={"telegram_title": title, "telegram_stats": extra})]
        return self.result(findings=findings, confidence=Confidence.MEDIUM,
                           source_url=url,
                           raw={"title": title, "description": desc, "extra": extra},
                           nodes=nodes)
