"""username_scan.py — large-scale public username enumeration.

Powered by the community WhatsMyName dataset (WebBreacher/WhatsMyName, vendored
in _wmn_data.json, NSFW sites removed). Given a handle, it checks HUNDREDS of
platforms for a PUBLIC profile with that name — the same thing Sherlock / Maigret
do, and the same thing you'd learn by opening each URL yourself.

GUARDRAIL: existence-of-a-public-profile only. It does not read private data,
and it does not tie a handle to a real-world identity.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client

_DATA = json.loads((Path(__file__).parent / "_wmn_data.json").read_text(encoding="utf-8"))
# Categories most relevant to mapping a person's public presence, checked first
# (and exclusively in the fast, non-deep pass).
_PRIORITY = ("social", "coding", "gaming", "tech", "music", "images", "video", "blog")


class UsernameScan(BaseModule):
    id = "username_scan"
    name = "Deep username scan (660+ sites)"
    description = "Sherlock-scale: checks 660+ platforms for a public profile with this handle."
    category = Category.SOCIAL
    inputs = (InputType.USERNAME, InputType.EMAIL)
    tier = "premium"
    timeout = 55.0

    async def _check(self, site: dict, user: str, sem: asyncio.Semaphore):
        url = site["u"].replace("{account}", user)
        async with sem:
            try:
                r = await get_client().get(url, timeout=7.0)
            except Exception:
                return None
        # WhatsMyName logic: present when the status matches e_code and (if given)
        # the e_string marker appears in the body.
        if r.status_code != site.get("c", 200):
            return None
        estr = site.get("e", "")
        if estr:
            try:
                if estr not in r.text[:120000]:
                    return None
            except Exception:
                return None
        return (site["n"], url, site.get("k", "misc"))

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        user = ctx.target.lstrip("@").strip()
        if "@" in user:
            user = user.split("@", 1)[0]
        if not user or len(user) < 2:
            res.ok = False; res.error = "username too short"; return res

        if ctx.deep:
            sites = _DATA                                   # all 660+
        else:
            sites = [s for s in _DATA if s.get("k") in _PRIORITY][:120]

        sem = asyncio.Semaphore(30)
        pairs = await asyncio.gather(*(self._check(s, user, sem) for s in sites))
        hits = [p for p in pairs if p]

        unode = res.node("username", user, label=f"@{user}")
        by_cat: dict[str, int] = {}
        for name, url, cat in sorted(hits):
            by_cat[cat] = by_cat.get(cat, 0) + 1
            res.add(name, url, Confidence.LIKELY, link=url)
            pn = res.node("profile", f"{name}:{user}", label=name)
            res.edge(unode.id, pn.id, "found_on")
        res.extra["found"] = len(hits)
        res.extra["checked"] = len(sites)
        top = ", ".join(f"{k} {v}" for k, v in sorted(by_cat.items(), key=lambda x: -x[1])[:4])
        res.summary = (f"Public profile on {len(hits)} of {len(sites)} platforms"
                       + (f" · {top}" if top else ""))
        return res
