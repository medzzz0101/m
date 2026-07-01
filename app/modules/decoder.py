"""
modules/decoder.py
==================
A "magic decoder" for suspicious/encoded strings — a tiny CyberChef-style helper.
Given a blob of text it tries common encodings (base64, base32, hex, URL-percent,
ROT13) and shows any that decode to readable text, so you can quickly peel back
an obfuscated value found in a URL, cookie, config or payload.

Pure stdlib, offline. Only decodes what you paste.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import urllib.parse

from app.core.base import (
    BaseModule, Category, Confidence, InputType, RunContext,
)


def _printable(b: bytes) -> str | None:
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return None
    printable = sum(1 for c in s if 32 <= ord(c) < 127 or c in "\n\t")
    if s and printable / len(s) > 0.85:
        return s
    return None


class DecoderModule(BaseModule):
    key = "decoder"
    name = "Magic decoder"
    category = Category.INTEL
    subtitle = "base64 / hex / URL / ROT13"
    accepts = (InputType.TEXT, InputType.HASH)
    needs_network = False
    description = (
        "Tries common encodings (base64/base32/hex/URL/ROT13) on a string and "
        "shows any that decode to readable text. Offline utility."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        results = []

        # base64
        try:
            dec = _printable(base64.b64decode(v + "=" * (-len(v) % 4), validate=False))
            if dec and dec != v:
                results.append(("base64", dec))
        except (binascii.Error, ValueError):
            pass
        # base32
        try:
            dec = _printable(base64.b32decode(v.upper() + "=" * (-len(v) % 8)))
            if dec and dec != v:
                results.append(("base32", dec))
        except (binascii.Error, ValueError):
            pass
        # hex
        try:
            if len(v) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in v):
                dec = _printable(bytes.fromhex(v))
                if dec and dec != v:
                    results.append(("hex", dec))
        except ValueError:
            pass
        # URL percent-encoding
        if "%" in v:
            dec = urllib.parse.unquote(v)
            if dec != v:
                results.append(("url", dec))
        # ROT13
        rot = codecs.encode(v, "rot13")
        if rot != v and rot.isascii():
            results.append(("rot13", rot))

        if not results:
            return self.result(
                findings=[{"label": "Decoder",
                           "summary": "No common encoding produced readable text."}],
                confidence=Confidence.INFO)

        findings = [{"label": f"{name}", "summary": dec[:400]} for name, dec in results]
        return self.result(findings=findings, confidence=Confidence.MEDIUM,
                           raw={"decodings": dict(results)})
