"""detect.py — turn a raw string into an InputType.

The rules are ordered from most-specific to least so, e.g., an email is never
mistaken for a username. This is deliberately simple and dependency-free; when
in doubt it falls back to USERNAME (for handles) or TEXT.
"""
from __future__ import annotations

import ipaddress
import re

from .base import InputType

# Pre-compiled patterns (compiled once at import for speed).
_EMAIL   = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN  = re.compile(r"^(?=.{1,253}$)([a-z0-9](-?[a-z0-9])*\.)+[a-z]{2,63}$", re.I)
_URL     = re.compile(r"^https?://", re.I)
_PHONE   = re.compile(r"^\+?[0-9][0-9\s().-]{6,}$")
_HASH    = re.compile(r"^[a-f0-9]{32}$|^[a-f0-9]{40}$|^[a-f0-9]{64}$", re.I)
_MMH3    = re.compile(r"^-?\d{5,12}$")               # favicon mmh3 (signed int)
_USER    = re.compile(r"^@?[a-z0-9][a-z0-9_.\-]{1,38}$", re.I)


def detect(raw: str) -> InputType:
    """Best-effort classification of a single-line target string."""
    s = (raw or "").strip()
    if not s:
        return InputType.UNKNOWN

    if _URL.match(s):
        return InputType.URL
    if _EMAIL.match(s):
        return InputType.EMAIL

    # IP literal (v4 or v6) — try the stdlib parser before regex heuristics.
    try:
        ipaddress.ip_address(s)
        return InputType.IP
    except ValueError:
        pass

    if _DOMAIN.match(s):
        return InputType.DOMAIN

    # Phone: must contain a plus or look like a long digit run, and have >=7 digits.
    digits = re.sub(r"\D", "", s)
    if _PHONE.match(s) and 7 <= len(digits) <= 15 and (s.startswith("+") or " " in s or "-" in s):
        return InputType.PHONE

    if _HASH.match(s):
        return InputType.HASH
    if _MMH3.match(s):
        return InputType.HASH

    if _USER.match(s):
        return InputType.USERNAME

    return InputType.TEXT


# Friendly labels for the UI's type pill.
TYPE_LABELS: dict[InputType, str] = {
    InputType.USERNAME: "username",
    InputType.EMAIL:    "email",
    InputType.DOMAIN:   "domain",
    InputType.IP:       "IP address",
    InputType.URL:      "URL",
    InputType.PHONE:    "phone",
    InputType.IMAGE:    "image",
    InputType.HASH:     "hash",
    InputType.TEXT:     "text",
    InputType.UNKNOWN:  "—",
}
