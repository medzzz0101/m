"""
modules/sun_calc.py
===================
Shadow-based geolocation helper. Given a date/time and a candidate location, it
computes the sun's AZIMUTH (compass bearing) and ELEVATION (height above the
horizon). Investigators use this to test a hypothesis: do the shadows in a photo
match where the sun WOULD have been at that place and time? If not, the claimed
location or time is wrong.

Pure astronomy math (NOAA solar position equations) — no dependencies, no
network. Input format (as free text / the input box):
    "YYYY-MM-DD HH:MM @ LAT,LON"   e.g.  "2023-06-21 14:30 @ 41.9,12.5"
(time is interpreted as UTC; add/subtract the location's offset yourself).
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)

INPUT_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})\s*@\s*"
    r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)")


def solar_position(dt: datetime, lat: float, lon: float) -> tuple[float, float]:
    """Return (azimuth_deg, elevation_deg) for the sun. dt must be UTC.
    Implements the NOAA solar-position algorithm (good to ~0.1°)."""
    # Fractional day-of-year.
    day = dt.timetuple().tm_yday
    hour = dt.hour + dt.minute / 60 + dt.second / 3600
    # Fractional year (radians).
    gamma = 2 * math.pi / 365 * (day - 1 + (hour - 12) / 24)
    # Equation of time (minutes) and solar declination (radians).
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma)
                       - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma)
                       - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    # True solar time (minutes).
    time_offset = eqtime + 4 * lon
    tst = hour * 60 + time_offset
    ha = math.radians(tst / 4 - 180)  # hour angle
    latr = math.radians(lat)
    # Solar zenith.
    cos_zen = (math.sin(latr) * math.sin(decl)
               + math.cos(latr) * math.cos(decl) * math.cos(ha))
    cos_zen = max(-1, min(1, cos_zen))
    zenith = math.acos(cos_zen)
    elevation = 90 - math.degrees(zenith)
    # Azimuth (clockwise from north).
    denom = math.cos(latr) * math.sin(zenith)
    if abs(denom) < 1e-9:
        azimuth = 0.0
    else:
        cos_az = (math.sin(latr) * math.cos(zenith) - math.sin(decl)) / denom
        cos_az = max(-1, min(1, cos_az))
        azimuth = math.degrees(math.acos(cos_az))
        if ha > 0:
            azimuth = 360 - azimuth
    return round(azimuth, 1), round(elevation, 1)


def _compass(deg: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW",
            "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[round(deg / 22.5) % 16]


class SunCalcModule(BaseModule):
    key = "sun_calc"
    name = "Sun position"
    category = Category.IMAGE
    subtitle = "Shadow-based geoloc helper"
    accepts = (InputType.TEXT,)
    needs_network = False
    description = (
        "Computes the sun's azimuth & elevation for a date/time + candidate "
        "location, to test whether shadows in a photo match. Input: "
        "'YYYY-MM-DD HH:MM @ LAT,LON' (UTC)."
    )

    async def run(self, value: str, ctx: RunContext):
        m = INPUT_RE.search(value.strip())
        if not m:
            return self.result(
                error="Format: 'YYYY-MM-DD HH:MM @ LAT,LON' (UTC). "
                      "Example: 2023-06-21 14:30 @ 41.90,12.50")
        date_s, time_s, lat_s, lon_s = m.groups()
        lat, lon = float(lat_s), float(lon_s)
        try:
            dt = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc)
        except ValueError as exc:
            return self.result(error=f"Bad date/time: {exc}")

        az, el = solar_position(dt, lat, lon)
        shadow_dir = (az + 180) % 360  # shadows fall opposite the sun
        below = el < 0

        findings = [
            {"label": "When (UTC)", "summary": dt.strftime("%Y-%m-%d %H:%M")},
            {"label": "Location", "summary": f"{lat}, {lon}"},
            {"label": "Sun azimuth", "summary": f"{az}° ({_compass(az)})"},
            {"label": "Sun elevation",
             "summary": f"{el}°" + (" — below horizon (night)" if below else ""),
             "confidence": "info" if not below else "low"},
            {"label": "Shadows point",
             "summary": f"{shadow_dir:.0f}° ({_compass(shadow_dir)}) "
                        f"— opposite the sun"},
            {"label": "How to use",
             "summary": "Compare this shadow bearing to the photo. A mismatch "
                        "means the claimed place/time is likely wrong.",
             "confidence": "info"},
            {"label": "Map", "map": {"lat": lat, "lon": lon,
                                     "label": f"sun az {az}° / el {el}°"}},
        ]
        nodes = [GraphNode("geo", f"{lat},{lon}", label=f"{lat},{lon}")]
        return self.result(findings=findings, confidence=Confidence.HIGH,
                           raw={"azimuth": az, "elevation": el,
                                "shadow_bearing": shadow_dir}, nodes=nodes)
