"""
modules/image_phash.py
======================
Compute perceptual hashes of an uploaded image. Unlike a cryptographic hash
(which changes completely if one pixel changes), a PERCEPTUAL hash stays similar
when the image is resized, re-compressed or lightly edited — so it's how you tell
"is this the same picture?" across copies. Useful for de-duplication, matching a
photo against a set, or confirming two images are versions of one another.

We implement aHash (average) and dHash (difference) with just Pillow — no extra
dependency — and return hex digests plus the raw bits. Offline.
"""

from __future__ import annotations

from PIL import Image

from app.core.base import (
    BaseModule, Category, Confidence, InputType, RunContext,
)


def _ahash(img: Image.Image, n: int = 8) -> str:
    g = img.convert("L").resize((n, n), Image.LANCZOS)
    px = list(g.getdata())
    avg = sum(px) / len(px)
    bits = "".join("1" if p >= avg else "0" for p in px)
    return f"{int(bits, 2):0{n*n//4}x}"


def _dhash(img: Image.Image, n: int = 8) -> str:
    g = img.convert("L").resize((n + 1, n), Image.LANCZOS)
    px = list(g.getdata())
    bits = ""
    for row in range(n):
        for col in range(n):
            left = px[row * (n + 1) + col]
            right = px[row * (n + 1) + col + 1]
            bits += "1" if left > right else "0"
    return f"{int(bits, 2):0{n*n//4}x}"


class ImagePhashModule(BaseModule):
    key = "image_phash"
    name = "Image perceptual hash"
    category = Category.IMAGE
    subtitle = "aHash / dHash for matching"
    accepts = (InputType.IMAGE, InputType.FILE)
    needs_network = False
    description = (
        "Computes perceptual hashes (aHash + dHash) that stay stable across "
        "resize/recompress — used to tell if two images are the same picture. "
        "Compare hashes by Hamming distance (small = similar)."
    )

    async def run(self, value: str, ctx: RunContext):
        path = ctx.upload_path
        if not path:
            return self.result(error="No uploaded image. Attach a file first.")
        try:
            img = Image.open(path)
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Not a readable image: {exc}")

        ah, dh = _ahash(img), _dhash(img)
        findings = [
            {"label": "aHash (average)", "summary": ah},
            {"label": "dHash (difference)", "summary": dh},
            {"label": "How to compare",
             "summary": "Two images are likely the same if the Hamming distance "
                        "between their dHashes is ≤ 10 bits.", "confidence": "info"},
        ]
        return self.result(findings=findings, confidence=Confidence.INFO,
                           raw={"ahash": ah, "dhash": dh})
