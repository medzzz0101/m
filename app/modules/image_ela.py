"""
modules/image_ela.py
====================
Error Level Analysis (ELA) — a classic image-forensics technique for spotting
manipulation. A JPEG loses a predictable amount of quality each time it's saved.
If part of an image was edited and re-saved, that region compresses at a DIFFERENT
error level than the rest. ELA re-saves the image at a known quality, diffs it
against the original, and amplifies the difference: edited/pasted regions tend to
"glow" brighter than untouched areas.

We return the ELA visualisation as an inline image plus a heuristic summary.
Offline, operates only on the file you provide. ELA is a LEAD, not proof.
"""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageChops, ImageEnhance

from app.core.base import (
    BaseModule, Category, Confidence, InputType, RunContext,
)


class ImageElaModule(BaseModule):
    key = "image_ela"
    name = "Image ELA (tamper)"
    category = Category.IMAGE
    subtitle = "Error-level manipulation check"
    accepts = (InputType.IMAGE, InputType.FILE)
    needs_network = False
    description = (
        "Error Level Analysis: re-compresses the image and amplifies the "
        "difference so edited/pasted regions stand out. A forensic lead for "
        "detecting manipulation — not definitive proof."
    )

    async def run(self, value: str, ctx: RunContext):
        path = ctx.upload_path
        if not path:
            return self.result(error="No uploaded image. Attach a file first.")
        try:
            orig = Image.open(path).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Not a readable image: {exc}")

        # Re-save at quality 90, reopen, diff.
        buf = io.BytesIO()
        orig.save(buf, "JPEG", quality=90)
        buf.seek(0)
        resaved = Image.open(buf).convert("RGB")
        ela = ImageChops.difference(orig, resaved)

        # Scale so the max difference maps to full brightness.
        extrema = ela.getextrema()
        max_diff = max(e[1] for e in extrema) or 1
        scale = 255.0 / max_diff
        ela = ImageEnhance.Brightness(ela).enhance(scale)

        # Downsize for a light inline preview and encode as PNG data-URL.
        preview = ela.copy()
        preview.thumbnail((520, 520))
        out = io.BytesIO()
        preview.save(out, "PNG")
        data_url = "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()

        # Heuristic: mean brightness of the ELA hints at overall recompression;
        # a very uneven ELA (high max vs. low mean) suggests localised edits.
        gray = ela.convert("L")
        hist = gray.histogram()
        total = sum(hist) or 1
        mean = sum(i * c for i, c in enumerate(hist)) / total
        bright_ratio = sum(hist[200:]) / total

        if bright_ratio > 0.02 and max_diff > 40:
            verdict = "Uneven error levels — some regions may have been edited. Inspect the bright areas."
            conf = Confidence.MEDIUM
        else:
            verdict = "Fairly uniform error levels — no obvious localised editing (or the image was flattened/re-saved once)."
            conf = Confidence.INFO

        findings = [
            {"label": "ELA verdict", "summary": verdict, "confidence": conf.value},
            {"label": "Max error level", "summary": str(max_diff)},
            {"label": "Mean / bright-ratio",
             "summary": f"{mean:.1f} / {bright_ratio*100:.1f}%"},
            {"label": "ELA visualisation",
             "summary": "Brighter = higher error level (possible edits).",
             "image": data_url},
            {"label": "Caveat",
             "summary": "ELA is suggestive, not conclusive. Screenshots, heavy "
                        "compression and resizing all affect it.", "confidence": "info"},
        ]
        return self.result(findings=findings, confidence=conf,
                           raw={"max_diff": max_diff, "mean": round(mean, 2),
                                "bright_ratio": round(bright_ratio, 4)})
