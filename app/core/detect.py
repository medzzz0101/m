"""
core/detect.py
==============
"What did the user actually type?"

Given a raw string, guess its InputType. This is what lets the user paste ANY
identifier into one box and have the engine route it to the right modules.

The checks are ordered most-specific -> least-specific so, e.g., a bitcoin
address is never mistaken for a plain username. The logic is deliberately
conservative and fully commented because false routing wastes a whole run.
"""

from __future__ import annotations

import ipaddress
import re

from .base import InputType

# --- Pre-compiled regexes (compiled once, reused) --------------------------

# ETH: 0x + 40 hex chars.
_ETH = re.compile(r"^0x[a-fA-F0-9]{40}$")

# BTC: legacy/p2sh base58 (1.. / 3..) OR bech32 (bc1..). Length-bounded to
# avoid matching random strings.
_BTC = re.compile(
    r"^(bc1[ac-hj-np-z02-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$"
)

# Generic hex hash (md5/sha1/sha256) — 32/40/64 hex chars.
_HASH = re.compile(r"^[a-fA-F0-9]{32}$|^[a-fA-F0-9]{40}$|^[a-fA-F0-9]{64}$")

# Email — simple but adequate for routing.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Domain — labels of letters/digits/hyphens, a real-ish TLD at the end.
_DOMAIN = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)

# MAC address — six hex octets separated by : or - (or bare 12 hex).
_MAC = re.compile(r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$")

# Phone — an optional +, then 7–15 digits with common separators.
_PHONE = re.compile(r"^\+?[0-9][0-9\s\-().]{5,18}[0-9]$")

# Username — what a handle usually looks like (no dots-as-domains, no @).
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{2,40}$")

# Common image / file extensions for when a filename is passed as text.
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".webp", ".gif")


def detect(value: str) -> InputType:
    """Return the best-guess InputType for `value`."""
    v = (value or "").strip()
    if not v:
        return InputType.TEXT

    # 1. URL — explicit scheme wins immediately.
    if v.lower().startswith(("http://", "https://")):
        return InputType.URL

    # 2. Crypto addresses (checked before hash/username — very specific shapes).
    if _ETH.match(v):
        return InputType.ETH_ADDRESS
    if _BTC.match(v):
        return InputType.BTC_ADDRESS

    # 3. IP address (v4 or v6) — let the stdlib decide authoritatively.
    try:
        ipaddress.ip_address(v)
        return InputType.IP
    except ValueError:
        pass

    # 4. Email.
    if _EMAIL.match(v):
        return InputType.EMAIL

    # 5. Filename that looks like an image.
    if v.lower().endswith(_IMAGE_EXT):
        return InputType.IMAGE

    # 6. Hash (after crypto, before domain/username — pure hex strings).
    if _HASH.match(v):
        return InputType.HASH

    # 6a. MAC address (six hex octets).
    if _MAC.match(v):
        return InputType.MAC

    # 6b. Phone number (optional +, mostly digits, 7–15 significant digits).
    digits = re.sub(r"\D", "", v)
    if _PHONE.match(v) and 7 <= len(digits) <= 15 and (
            v.startswith("+") or not v.isalnum() or v.isdigit()):
        # Avoid grabbing short pure-digit "usernames": require 7+ digits (above).
        return InputType.PHONE

    # 7. Domain (has a dot, valid label structure).
    if "." in v and _DOMAIN.match(v):
        return InputType.DOMAIN

    # 8. Username (no dots / single token).
    if _USERNAME.match(v):
        return InputType.USERNAME

    # 9. Fallback.
    return InputType.TEXT


# Friendly metadata used by the UI to show what it detected.
TYPE_LABELS: dict[InputType, str] = {
    InputType.USERNAME: "Username",
    InputType.EMAIL: "Email",
    InputType.DOMAIN: "Domain",
    InputType.IP: "IP address",
    InputType.URL: "URL",
    InputType.BTC_ADDRESS: "Bitcoin address",
    InputType.ETH_ADDRESS: "Ethereum address",
    InputType.IMAGE: "Image",
    InputType.FILE: "File",
    InputType.TEXT: "Text",
    InputType.HASH: "Hash",
    InputType.PHONE: "Phone",
    InputType.MAC: "MAC address",
}
