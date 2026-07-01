"""
modules/greynoise.py
====================
Classify an IP with GreyNoise's free Community API (no key): is it "noise" (a mass
internet scanner / crawler that hits everyone), or "RIOT" (a common business
service like a CDN or public DNS that's safe to ignore)? This is invaluable
triage — it tells you whether an IP touching your infrastructure is targeted or
just background internet noise.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json, resolve_ip


class GreyNoiseModule(BaseModule):
    key = "greynoise"
    name = "GreyNoise"
    category = Category.INTEL
    subtitle = "Scanner / RIOT classification"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    description = (
        "GreyNoise Community classification for an IP: mass-scanner 'noise' vs "
        "benign business 'RIOT' service, with the actor name when known."
    )

    async def run(self, value: str, ctx: RunContext):
        ip = await resolve_ip(value.strip())
        if not ip:
            return self.result(error=f"Could not resolve '{value}'.")
        url = f"https://api.greynoise.io/v3/community/{ip}"
        try:
            data = await fetch_json(ctx, url, ttl=21600, namespace="greynoise",
                                    headers={"User-Agent": "osint-engine"})
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"GreyNoise failed: {exc}", source_url=url)

        noise = data.get("noise")
        riot = data.get("riot")
        classification = data.get("classification")
        name = data.get("name")

        findings = [
            {"label": "Classification",
             "summary": (classification or "unknown").upper(),
             "confidence": "high" if classification else "info"},
            {"label": "Scanner (noise)", "summary": "yes" if noise else "no"},
            {"label": "Benign service (RIOT)", "summary": "yes" if riot else "no"},
            {"label": "Actor / provider", "summary": name or "—"},
            {"label": "Assessment", "summary": data.get("message", "")},
        ]
        conf = (Confidence.MEDIUM if classification == "malicious"
                else Confidence.INFO)
        return self.result(
            findings=findings, confidence=conf,
            source_url=f"https://viz.greynoise.io/ip/{ip}",
            raw=data,
            nodes=[GraphNode("ip", ip, props={"greynoise": classification,
                                              "noise": noise, "riot": riot})],
        )
