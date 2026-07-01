"""
modules/web_screenshot.py
=========================
Capture a live screenshot of a website and show it inline in the result card.
A visual snapshot is a genuinely useful recon artifact: you see branding, a login
portal, a parked page, a defacement or a "site for sale" instantly — without
opening the target yourself, and it's preserved as evidence.

We drive the pre-installed headless Chromium as a subprocess (through the egress
proxy). Rendering a public page is exactly what a browser does — no interaction,
no exploitation.
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import host_of

CHROME_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
]


def _find_chrome() -> str | None:
    # Honour an explicit override, then known locations, then a glob.
    env = os.environ.get("CHROME_BIN")
    if env and os.path.exists(env):
        return env
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    import glob
    hits = glob.glob("/opt/pw-browsers/chromium*/chrome-linux/chrome")
    return hits[0] if hits else None


class WebScreenshotModule(BaseModule):
    key = "web_screenshot"
    name = "Website screenshot"
    category = Category.INFRASTRUCTURE
    subtitle = "Live visual snapshot"
    accepts = (InputType.DOMAIN, InputType.URL, InputType.IP)
    needs_network = True
    description = (
        "Renders the target in headless Chromium and returns a screenshot of the "
        "live page — instant visual context (portal, parked page, branding…)."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        url = v if v.startswith(("http://", "https://")) else f"https://{v}"
        chrome = _find_chrome()
        if not chrome:
            return self.result(error="No Chromium binary found in this environment.")

        proxy = os.environ.get("HTTPS_PROXY", "")
        out = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        args = [
            chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--hide-scrollbars", "--disable-dev-shm-usage",
            "--ignore-certificate-errors", "--virtual-time-budget=8000",
            f"--screenshot={out}", "--window-size=1280,800",
        ]
        if proxy:
            args.append(f"--proxy-server={proxy}")
        args.append(url)

        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.communicate(), timeout=35)
        except asyncio.TimeoutError:
            try: proc.kill()
            except Exception: pass
            return self.result(error="Screenshot timed out.", source_url=url)
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Chromium failed: {exc}", source_url=url)

        if not os.path.exists(out) or os.path.getsize(out) == 0:
            return self.result(error="No screenshot produced (site unreachable?).",
                               source_url=url)
        try:
            with open(out, "rb") as fh:
                data = fh.read()
        finally:
            try: os.unlink(out)
            except Exception: pass

        data_url = "data:image/png;base64," + base64.b64encode(data).decode()
        host = host_of(url)
        findings = [
            {"label": "Captured", "summary": f"{url}  ·  {len(data)//1024} KB"},
            {"label": "Snapshot", "summary": "Live rendered page:", "image": data_url},
        ]
        return self.result(
            findings=findings, confidence=Confidence.HIGH, source_url=url,
            raw={"url": url, "bytes": len(data)},
            nodes=[GraphNode("domain", host, props={"screenshot": True})],
        )
