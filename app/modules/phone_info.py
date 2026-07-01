"""
modules/phone_info.py
=====================
Metadata for a phone NUMBER (PhoneInfoga-style), derived purely from the number
itself with Google's libphonenumber data: whether it's valid/possible, the
country and region, the likely carrier, the line type (mobile/fixed/VoIP…), and
the time zone(s). Plus ready-to-run public search links.

IMPORTANT / GUARDRAIL: this reports what a number's STRUCTURE tells you — country,
carrier, type — the same as a numbering-plan lookup. It does NOT, and will not,
resolve a number to its OWNER, their name, address, or accounts. That's the hard
line; this is number metadata only.
"""

from __future__ import annotations

from urllib.parse import quote

import phonenumbers
from phonenumbers import carrier, geocoder, timezone

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)

TYPE_NAMES = {
    0: "Fixed line", 1: "Mobile", 2: "Fixed line or mobile", 3: "Toll-free",
    4: "Premium rate", 5: "Shared cost", 6: "VoIP", 7: "Personal number",
    8: "Pager", 9: "UAN", 10: "Unknown", 27: "Emergency", 28: "Voicemail",
}


class PhoneInfoModule(BaseModule):
    key = "phone_info"
    name = "Phone number info"
    category = Category.IDENTITY
    subtitle = "Country / carrier / type"
    accepts = (InputType.PHONE,)
    needs_network = False
    description = (
        "Metadata for a phone number (validity, country, carrier, line type, time "
        "zone) from libphonenumber, plus public search links. Number metadata only "
        "— never the owner's identity."
    )

    async def run(self, value: str, ctx: RunContext):
        raw = value.strip()
        num_str = raw if raw.startswith("+") else "+" + raw.lstrip("00")
        try:
            n = phonenumbers.parse(num_str, None)
        except Exception:
            # Retry assuming it needs a default region is ambiguous; report clearly.
            return self.result(error="Could not parse the number. Include the "
                                     "country code, e.g. +14155552671.")

        valid = phonenumbers.is_valid_number(n)
        possible = phonenumbers.is_possible_number(n)
        e164 = phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
        intl = phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        region = geocoder.description_for_number(n, "en")
        car = carrier.name_for_number(n, "en")
        ltype = TYPE_NAMES.get(phonenumbers.number_type(n), "Unknown")
        tzs = timezone.time_zones_for_number(n)
        cc = n.country_code

        findings = [
            {"label": "Valid", "summary": "yes" if valid else
             ("possible but not valid" if possible else "no"),
             "confidence": "high" if valid else "low"},
            {"label": "E.164", "summary": e164},
            {"label": "International", "summary": intl},
            {"label": "Country code", "summary": f"+{cc}"},
            {"label": "Region", "summary": region or "—"},
            {"label": "Carrier (best guess)", "summary": car or "— (not available)"},
            {"label": "Line type", "summary": ltype},
            {"label": "Time zone(s)", "summary": ", ".join(tzs) or "—"},
        ]
        # Public OSINT search links (the user runs them; no owner lookup here).
        digits = e164.lstrip("+")
        findings.append({
            "label": "Public searches",
            "values": [
                f"https://www.google.com/search?q=%22{quote(e164)}%22",
                f"https://www.google.com/search?q=%22{quote(intl)}%22",
                f"https://t.me/+{digits}",
            ],
            "note": "Search the number as a string to see where the OWNER may have "
                    "PUBLISHED it themselves (ads, listings) — this tool does not "
                    "resolve the owner."})
        findings.append({"label": "Scope",
                         "summary": "Number metadata only — never owner identity, "
                                    "location or accounts.", "confidence": "info"})

        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if valid else Confidence.INFO,
            raw={"e164": e164, "valid": valid, "region": region, "carrier": car,
                 "type": ltype, "timezones": list(tzs)},
            nodes=[GraphNode("username", e164, label=e164,
                             props={"kind": "phone", "region": region})],
        )
