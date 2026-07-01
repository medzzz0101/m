"""
modules/image_meta.py
=====================
Full metadata dump for an uploaded image — the wider companion to exif_gps.
Where exif_gps focuses on the geotag, this surfaces EVERYTHING: camera make/model,
lens, exposure/ISO, software used to edit, timestamps, orientation, colour
profile and dimensions. Editing software + timestamps are strong authenticity /
forensic signals.

Pillow reads dimensions/format; exifread reads the rich EXIF/MakerNote tags.
No network — operates purely on the file you provided.
"""

from __future__ import annotations

import exifread
from PIL import Image

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)

# Tags we promote to headline findings (the rest go in the raw drawer).
HEADLINE = {
    "Image Make": "Camera make",
    "Image Model": "Camera model",
    "EXIF LensModel": "Lens",
    "Image Software": "Software",
    "EXIF DateTimeOriginal": "Captured",
    "Image DateTime": "Modified",
    "EXIF ExposureTime": "Exposure",
    "EXIF FNumber": "Aperture",
    "EXIF ISOSpeedRatings": "ISO",
    "EXIF FocalLength": "Focal length",
    "Image Orientation": "Orientation",
}


class ImageMetaModule(BaseModule):
    key = "image_meta"
    name = "Image metadata"
    category = Category.IMAGE
    subtitle = "Camera, software, timestamps"
    accepts = (InputType.IMAGE, InputType.FILE)
    needs_network = False
    description = (
        "Full image metadata: camera/lens, exposure settings, editing software, "
        "timestamps, orientation and dimensions. Software + times are forensic "
        "authenticity signals."
    )

    async def run(self, value: str, ctx: RunContext):
        path = ctx.upload_path
        if not path:
            return self.result(error="No uploaded image. Attach a file first.")

        findings: list[dict] = []
        raw: dict = {}

        # Pillow: format + dimensions + basic info.
        try:
            with Image.open(path) as im:
                findings.append({"label": "Format",
                                 "summary": f"{im.format} · {im.width}×{im.height}"
                                            f" · {im.mode}"})
                raw["pillow"] = {"format": im.format, "size": im.size, "mode": im.mode,
                                 "info_keys": list(im.info.keys())}
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Not a readable image: {exc}")

        # exifread: rich tags.
        try:
            with open(path, "rb") as fh:
                tags = exifread.process_file(fh, details=False)
        except Exception:
            tags = {}

        for tag, label in HEADLINE.items():
            if tag in tags:
                findings.append({"label": label, "summary": str(tags[tag])})

        raw["exif"] = {k: str(v) for k, v in tags.items()
                       if not k.startswith("JPEGThumbnail")}

        # A tiny authenticity note when editing software is present.
        sw = tags.get("Image Software")
        if sw and any(x in str(sw).lower() for x in
                      ("photoshop", "gimp", "lightroom", "affinity", "snapseed")):
            findings.append({"label": "Note",
                             "summary": f"Edited with {sw} — pixels may not be original.",
                             "confidence": "medium"})

        if len(findings) <= 1:
            findings.append({"label": "EXIF",
                             "summary": "No EXIF metadata (likely stripped)."})

        nodes = [GraphNode("image", path.split("/")[-1])]
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if len(tags) else Confidence.INFO,
            raw=raw, nodes=nodes,
        )
