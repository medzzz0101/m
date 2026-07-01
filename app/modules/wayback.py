"""
modules/wayback.py
==================
Check the Internet Archive (Wayback Machine) for historical snapshots of a
domain/URL. Old captures reveal a site's past — previous tech, staff pages,
exposed content, prior IPs — and give you a citable, time-stamped record.

Uses archive.org's public availability API (no key).
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json, host_of


class WaybackModule(BaseModule):
    key = "wayback"
    name = "Wayback Machine"
    category = Category.INTEL
    subtitle = "Archived snapshots"
    accepts = (InputType.DOMAIN, InputType.URL)
    needs_network = True
    description = (
        "Looks up Internet Archive snapshots for a domain/URL — the closest "
        "archived capture and a link to browse its full history."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        target = v if v.startswith("http") else f"https://{v}"
        host = host_of(target)
        try:
            data = await fetch_json(
                ctx, f"https://archive.org/wayback/available?url={host}",
                ttl=3600, namespace="wayback")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Wayback lookup failed: {exc}", source_url=target)

        snap = (data.get("archived_snapshots") or {}).get("closest") or {}
        history = f"https://web.archive.org/web/*/{host}"
        if snap.get("available"):
            ts = snap.get("timestamp", "")
            pretty = (f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}"
                      if len(ts) >= 12 else ts)
            findings = [
                {"label": "Archived", "summary": f"Yes — closest capture {pretty}",
                 "confidence": "high"},
                {"label": "Closest snapshot", "values": [snap.get("url", "")]},
                {"label": "Full history", "values": [history]},
            ]
            conf = Confidence.HIGH
        else:
            findings = [
                {"label": "Archived", "summary": "No snapshots found for this host."},
                {"label": "Try history", "values": [history]},
            ]
            conf = Confidence.INFO
        return self.result(findings=findings, confidence=conf, source_url=history,
                           raw=data, nodes=[GraphNode("domain", host)])
