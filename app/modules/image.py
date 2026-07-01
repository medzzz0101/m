"""image.py — image forensics & geolocation aids (works on YOUR uploads).

These operate on a locally uploaded image: reading EXIF metadata, extracting
embedded GPS coordinates the photographer left in the file, estimating sun
position for a claimed time/place, and simple tamper-hint checks. No face
recognition, no reverse-identifying people — geolocation aids for an image,
Bellingcat-style.
"""
from __future__ import annotations

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)


def _needs_image(res: ModuleResult, ctx: RunContext) -> bool:
    if not ctx.upload_path:
        res.ok = False
        res.error = "no image uploaded"
        return False
    return True


class ExifData(BaseModule):
    id = "exif_data"
    name = "EXIF metadata"
    description = "Reads camera, timestamps and settings embedded in an uploaded image."
    category = Category.IMAGE
    inputs = (InputType.IMAGE,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import exifread
        res = self.result()
        if not _needs_image(res, ctx): return res
        with open(ctx.upload_path, "rb") as f:
            tags = exifread.process_file(f, details=False)
        if not tags:
            res.summary = "No EXIF metadata present (may have been stripped)"; return res
        interesting = {
            "Image Make": "Camera make", "Image Model": "Camera model",
            "EXIF DateTimeOriginal": "Taken (original)", "Image DateTime": "Modified",
            "EXIF LensModel": "Lens", "EXIF FNumber": "Aperture",
            "EXIF ExposureTime": "Shutter", "EXIF ISOSpeedRatings": "ISO",
            "EXIF FocalLength": "Focal length", "Image Software": "Software",
            "Image Orientation": "Orientation",
        }
        for tag, label in interesting.items():
            if tag in tags:
                res.add(label, str(tags[tag]), Confidence.CONFIRMED)
        res.summary = f"{len(res.findings)} EXIF fields recovered"
        return res


class ExifGps(BaseModule):
    id = "exif_gps"
    name = "GPS geotag"
    description = "Extracts GPS coordinates a camera embedded in the photo and maps them."
    category = Category.IMAGE
    inputs = (InputType.IMAGE,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        import exifread
        res = self.result()
        if not _needs_image(res, ctx): return res
        with open(ctx.upload_path, "rb") as f:
            tags = exifread.process_file(f)

        def dms_to_deg(vals, ref):
            d = float(vals[0].num) / vals[0].den
            m = float(vals[1].num) / vals[1].den
            s = float(vals[2].num) / vals[2].den
            deg = d + m / 60 + s / 3600
            if ref in ("S", "W"): deg = -deg
            return deg

        lat = tags.get("GPS GPSLatitude"); latr = tags.get("GPS GPSLatitudeRef")
        lon = tags.get("GPS GPSLongitude"); lonr = tags.get("GPS GPSLongitudeRef")
        if not (lat and lon and latr and lonr):
            res.summary = "No GPS geotag in this image"; return res
        la = dms_to_deg(lat.values, str(latr)); lo = dms_to_deg(lon.values, str(lonr))
        res.node("geo", f"{la:.5f},{lo:.5f}", label="photo location")
        res.add("Latitude", f"{la:.6f}", Confidence.CONFIRMED)
        res.add("Longitude", f"{lo:.6f}", Confidence.CONFIRMED)
        res.add("Map", f"https://www.openstreetmap.org/?mlat={la}&mlon={lo}#map=16/{la}/{lo}",
                Confidence.INFO, link=f"https://www.openstreetmap.org/?mlat={la}&mlon={lo}#map=16/{la}/{lo}")
        if tags.get("GPS GPSAltitude"):
            res.add("Altitude", str(tags["GPS GPSAltitude"]), Confidence.LIKELY)
        res.extra["map"] = {"lat": la, "lon": lo, "label": "Photo geotag"}
        res.summary = f"Geotag: {la:.5f}, {lo:.5f}"
        return res


class ImageInfo(BaseModule):
    id = "image_info"
    name = "Image properties"
    description = "Dimensions, format, mode and a tamper hint from the file structure."
    category = Category.IMAGE
    inputs = (InputType.IMAGE,)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        from PIL import Image
        res = self.result()
        if not _needs_image(res, ctx): return res
        with Image.open(ctx.upload_path) as im:
            res.add("Format", im.format, Confidence.CONFIRMED)
            res.add("Dimensions", f"{im.width} × {im.height}", Confidence.CONFIRMED)
            res.add("Mode", im.mode, Confidence.INFO)
            res.add("Megapixels", f"{im.width*im.height/1e6:.1f} MP", Confidence.INFO)
            if "exif" in im.info:
                res.add("EXIF present", "yes", Confidence.CONFIRMED)
            if im.info.get("Software"):
                res.add("Software marker", im.info["Software"], Confidence.LIKELY)
        res.summary = "Image properties read"
        return res


class ImageEla(BaseModule):
    id = "image_ela"
    name = "Error-level analysis"
    description = "Highlights recompression differences that can hint at edited regions."
    category = Category.IMAGE
    inputs = (InputType.IMAGE,)
    tier = "elite"
    timeout = 20.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        from PIL import Image, ImageChops
        import io, base64
        res = self.result()
        if not _needs_image(res, ctx): return res
        with Image.open(ctx.upload_path) as im:
            im = im.convert("RGB")
            buf = io.BytesIO(); im.save(buf, "JPEG", quality=90); buf.seek(0)
            recompressed = Image.open(buf)
            ela = ImageChops.difference(im, recompressed)
            extrema = ela.getextrema()
            max_diff = max(e[1] for e in extrema) or 1
            scale = 255.0 / max_diff
            ela = ela.point(lambda p: min(255, int(p * scale)))
            out = io.BytesIO(); ela.save(out, "PNG"); out.seek(0)
            b64 = base64.b64encode(out.read()).decode()
        res.add("Max error level", str(max_diff), Confidence.INFO)
        res.add("Interpretation",
                "uniform = likely untouched; bright patches = candidate edits",
                Confidence.POSSIBLE)
        res.extra["image_b64"] = f"data:image/png;base64,{b64}"
        res.summary = "ELA map generated"
        return res


class SunPosition(BaseModule):
    id = "sun_position"
    name = "Sun position (shadow check)"
    description = "Sun azimuth/elevation for a lat,lon + time — verify shadows in a photo."
    category = Category.IMAGE
    inputs = (InputType.TEXT,)
    tier = "premium"

    async def run(self, ctx: RunContext) -> ModuleResult:
        # Input format: "lat,lon,YYYY-MM-DDTHH:MM" (UTC). Pure astronomy, no deps.
        import datetime as dt, math
        res = self.result()
        try:
            parts = ctx.target.split(",")
            lat = float(parts[0]); lon = float(parts[1])
            when = dt.datetime.fromisoformat(parts[2]) if len(parts) > 2 else dt.datetime.utcnow()
        except Exception:
            res.ok = False
            res.error = "expected 'lat,lon,YYYY-MM-DDTHH:MM' (UTC)"
            return res
        # NOAA-style solar position approximation.
        n = when.timetuple().tm_yday
        frac_hour = when.hour + when.minute / 60
        decl = -23.44 * math.cos(math.radians(360/365 * (n + 10)))
        hour_angle = (frac_hour - 12) * 15 + lon
        latr = math.radians(lat); dr = math.radians(decl); hr = math.radians(hour_angle)
        elev = math.degrees(math.asin(
            math.sin(latr)*math.sin(dr) + math.cos(latr)*math.cos(dr)*math.cos(hr)))
        az = math.degrees(math.atan2(-math.sin(hr),
            math.tan(dr)*math.cos(latr) - math.sin(latr)*math.cos(hr)))
        az = (az + 360) % 360
        res.add("Date/time (UTC)", when.isoformat(), Confidence.INFO)
        res.add("Sun elevation", f"{elev:.1f}°", Confidence.LIKELY)
        res.add("Sun azimuth", f"{az:.1f}° (from N)", Confidence.LIKELY)
        res.add("Shadow direction", f"{(az+180)%360:.0f}° (opposite the sun)", Confidence.LIKELY)
        res.add("Daylight", "yes" if elev > 0 else "no (sun below horizon)",
                Confidence.CONFIRMED)
        res.summary = f"Sun elev {elev:.1f}°, az {az:.1f}°"
        return res


class GeoChecklist(BaseModule):
    id = "geo_checklist"
    name = "Geolocation checklist"
    description = "A structured Bellingcat-style checklist of clues to look for in an image."
    category = Category.IMAGE
    inputs = (InputType.IMAGE, InputType.TEXT)
    tier = "base"

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        checklist = [
            ("Language / script", "signage, plates, ads → country/region"),
            ("Vegetation & terrain", "climate zone, hemisphere by season"),
            ("Architecture", "building style, roofing, power-line type"),
            ("Vehicles", "plate format, side of the road, taxi colours"),
            ("Sun & shadows", "use the sun-position module to check time-of-day"),
            ("Landmarks", "towers, mountains, coastlines → reverse image / maps"),
            ("Road markings", "line colours, crossing style differ by country"),
            ("Business names", "search names/phone numbers on maps"),
        ]
        for k, v in checklist:
            res.add(k, v, Confidence.INFO)
        res.summary = "Geolocation checklist — work top to bottom"
        return res
