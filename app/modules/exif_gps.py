"""
modules/exif_gps.py
===================
Pull EXIF metadata — especially GPS — out of an image the USER uploaded, so it
can be plotted on the Leaflet/OSM map and reverse-geocoded.

This is the friendly, high-signal start of the image-geolocation domain. Many
photos shared online have GPS stripped (social platforms remove it); when that
happens we say so plainly rather than implying we found nothing interesting.

Reverse-geocoding uses OpenStreetMap Nominatim (public, must send a UA and be
polite — we cache aggressively).
"""

from __future__ import annotations

import exifread

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


def _ratio_to_float(ratio) -> float:
    """exifread returns Ratio objects; convert to float safely."""
    try:
        return float(ratio.num) / float(ratio.den)
    except Exception:
        return float(ratio)


def _dms_to_decimal(dms, ref) -> float | None:
    """Convert EXIF degrees/minutes/seconds + N/S/E/W ref to signed decimal."""
    try:
        d = _ratio_to_float(dms[0])
        m = _ratio_to_float(dms[1])
        s = _ratio_to_float(dms[2])
        dec = d + m / 60.0 + s / 3600.0
        if ref in ("S", "W"):
            dec = -dec
        return round(dec, 6)
    except Exception:
        return None


class ExifGpsModule(BaseModule):
    key = "exif_gps"
    name = "EXIF & GPS"
    category = Category.IMAGE
    subtitle = "Geotag → map + reverse-geocode"
    accepts = (InputType.IMAGE, InputType.FILE)
    needs_network = True  # only for the optional reverse-geocode step
    requires_authorized_target = False
    description = (
        "Extracts EXIF metadata from an uploaded image, decodes GPS coordinates, "
        "plots them on the map, and reverse-geocodes the location. Clearly notes "
        "when metadata has been stripped."
    )

    async def run(self, value: str, ctx: RunContext):
        path = ctx.upload_path
        if not path:
            return self.result(
                error="No uploaded image. Use the upload control to attach a file.",
            )

        # exifread reads the file synchronously; images are small so this is fine.
        try:
            with open(path, "rb") as fh:
                tags = exifread.process_file(fh, details=False)
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Could not read image: {exc}")

        # --- Camera / capture context -------------------------------------
        def t(name):
            return str(tags[name]) if name in tags else None

        make, model = t("Image Make"), t("Image Model")
        software = t("Image Software")
        taken = t("EXIF DateTimeOriginal") or t("Image DateTime")

        findings: list[dict] = []
        nodes: list[GraphNode] = [GraphNode("image", path.split("/")[-1])]
        edges: list[GraphEdge] = []

        if make or model:
            findings.append({"label": "Camera",
                             "summary": " ".join(filter(None, [make, model]))})
        if software:
            findings.append({"label": "Software", "summary": software})
        if taken:
            findings.append({"label": "Taken", "summary": taken})

        # --- GPS -----------------------------------------------------------
        lat = lon = None
        if "GPS GPSLatitude" in tags and "GPS GPSLongitude" in tags:
            lat = _dms_to_decimal(
                tags["GPS GPSLatitude"].values,
                str(tags.get("GPS GPSLatitudeRef", "N")),
            )
            lon = _dms_to_decimal(
                tags["GPS GPSLongitude"].values,
                str(tags.get("GPS GPSLongitudeRef", "E")),
            )

        place = None
        if lat is not None and lon is not None:
            findings.append({"label": "GPS", "summary": f"{lat}, {lon}",
                             "confidence": "high"})
            # Reverse geocode (best-effort, cached).
            try:
                geo = await fetch_json(
                    ctx,
                    f"https://nominatim.openstreetmap.org/reverse?format=json"
                    f"&lat={lat}&lon={lon}&zoom=16",
                    ttl=604800, namespace="nominatim",
                    headers={"User-Agent": "osint-engine/1.0 (self-hosted)"},
                )
                place = geo.get("display_name")
                if place:
                    findings.append({"label": "Reverse-geocode", "summary": place})
            except Exception:
                pass

            geo_id = f"{lat},{lon}"
            nodes.append(GraphNode("geo", geo_id, label=place or geo_id,
                                   props={"lat": lat, "lon": lon, "place": place}))
            edges.append(GraphEdge(f"image:{path.split('/')[-1]}",
                                   f"geo:{geo_id}", "located_at"))
            # `map` block: the frontend renders any finding carrying lat/lon on Leaflet.
            findings.append({"label": "Map", "map": {"lat": lat, "lon": lon,
                                                     "label": place or geo_id}})
        else:
            findings.append({
                "label": "GPS",
                "summary": "No GPS metadata present.",
                "confidence": "info",
                "note": "Geotag is absent — either the camera didn't record it "
                        "or it was stripped (most social platforms strip EXIF on "
                        "upload). This is normal and not a failure.",
            })

        has_gps = lat is not None
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if has_gps else Confidence.INFO,
            raw={"tags": {k: str(v) for k, v in tags.items()
                          if not k.startswith("JPEGThumbnail")}},
            nodes=nodes,
            edges=edges,
        )
