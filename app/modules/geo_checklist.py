"""
modules/geo_checklist.py
========================
A structured CLUE CHECKLIST that guides manual visual geolocation — the
Bellingcat-style discipline of reading a photo. It doesn't call any API; it turns
the messy skill of "where was this taken?" into an ordered set of things to look
for, each with what it can tell you and how to search it.

This is intentionally offline and deterministic: it's a thinking tool.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, InputType, RunContext,
)

CHECKLIST = [
    ("Language & script", "Signs, posters, graffiti. Script narrows to a region; "
     "specific language/dialect narrows further.",
     "Type visible text into a translator; identify the script."),
    ("Road markings", "Line colours, centre-line style, crossing patterns and "
     "kerb paint differ by country.",
     "Compare against 'road markings by country' references."),
    ("License plates", "Plate shape, colour, aspect ratio and character format "
     "are country- (often region-) specific.",
     "Match plate format to a national plate guide."),
    ("Traffic infrastructure", "Sign shapes, traffic-light housing, bollards, "
     "utility-pole style, guard-rail type.",
     "Cross-reference sign shape (e.g. octagon vs. inverted-triangle)."),
    ("Driving side", "Which side vehicles drive on halves the world map.",
     "Note traffic direction and steering-wheel side."),
    ("Architecture", "Roof pitch/material, window style, balconies, building "
     "material and colour reflect climate + culture.",
     "Compare to regional architecture references."),
    ("Vegetation & terrain", "Tree species, crops, soil colour, mountains vs. "
     "plains, aridity — constrains latitude/climate.",
     "Identify plant species; match to climate zones."),
    ("Sun & shadows", "Shadow direction + length gives hemisphere and a rough "
     "time — combine with the Sun-position module.",
     "Run the sun_calc module with candidate coordinates."),
    ("Business names / phone numbers", "Storefronts, ads, phone country/area "
     "codes and web domains are highly localising.",
     "Search the business name; note the phone country code / TLD."),
    ("Utility & antenna markings", "Operator logos on poles, manhole covers, "
     "and antennas identify the local utility/telecom.",
     "Search the operator name to place the region."),
]


class GeoChecklistModule(BaseModule):
    key = "geo_checklist"
    name = "Geolocation checklist"
    category = Category.IMAGE
    subtitle = "Guided visual clue hunt"
    accepts = (InputType.IMAGE, InputType.FILE, InputType.TEXT)
    needs_network = False
    description = (
        "A structured checklist of visual clues (signage, plates, road markings, "
        "architecture, vegetation, sun) to guide manual image geolocation."
    )

    async def run(self, value: str, ctx: RunContext):
        findings = [{
            "label": "Method",
            "summary": "Work top-to-bottom. Each clue narrows the map; combine "
                       "several to converge. Nothing here leaves your device.",
            "confidence": "info",
        }]
        for i, (title, why, how) in enumerate(CHECKLIST, 1):
            findings.append({
                "label": f"{i}. {title}",
                "summary": why,
                "note": f"→ {how}",
            })
        return self.result(findings=findings, confidence=Confidence.INFO,
                           raw={"items": [c[0] for c in CHECKLIST]})
