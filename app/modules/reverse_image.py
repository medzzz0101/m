"""
modules/reverse_image.py
========================
Reverse-image-search launchpad. Reverse image search is one of the highest-value
OSINT moves for a photo (find where else it appears, the original source, other
angles). The major engines need you to submit the image on their own site, so
this module builds the one-tap links to each engine and lays out the workflow.

Offline: it prepares the search — you run it on the engine of your choice.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, InputType, RunContext,
)

ENGINES = [
    ("Google Lens", "https://lens.google.com/uploadbyurl?url="),
    ("Yandex (best for faces/places)", "https://yandex.com/images/search?rpt=imageview&url="),
    ("Bing Visual Search", "https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:"),
    ("TinEye (finds first appearance)", "https://tineye.com/search?url="),
]


class ReverseImageModule(BaseModule):
    key = "reverse_image"
    name = "Reverse image search"
    category = Category.IMAGE
    subtitle = "Google/Yandex/Bing/TinEye"
    accepts = (InputType.IMAGE, InputType.URL, InputType.FILE)
    needs_network = False
    description = (
        "Prepares reverse-image searches across Google Lens, Yandex, Bing and "
        "TinEye to find where a photo appears online, its source and other copies."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        is_url = v.startswith("http")

        findings = [{
            "label": "How to use",
            "summary": ("Your image already has a public URL — the links below "
                        "run the search directly." if is_url else
                        "Upload the image to each engine (or host it and paste the "
                        "URL). Yandex is best for faces/landmarks; TinEye finds the "
                        "earliest appearance."),
            "confidence": "info",
        }]
        for name, prefix in ENGINES:
            link = (prefix + v) if is_url else prefix.split("?")[0].rstrip("=")
            findings.append({"label": name,
                             "summary": "one-tap search" if is_url else "open engine",
                             "values": [link]})
        findings.append({
            "label": "Tip",
            "summary": "Crop to a distinctive detail (a sign, logo, skyline) and "
                       "search that too — it often beats the full image.",
            "confidence": "info"})
        return self.result(findings=findings, confidence=Confidence.INFO,
                           raw={"is_url": is_url})
