"""
modules/hash_identify.py
========================
Identify the likely TYPE of a hash from its length and character set (MD5, SHA-1,
SHA-256/512, NTLM, bcrypt, CRC, etc.). Handy first step when you find an unknown
hash in a config, database dump you own, or CTF challenge — it tells you what
algorithm produced it (so you know what you're dealing with).

Offline pattern analysis only. It does NOT crack or look up the hash.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, InputType, RunContext,
)

HEX = re.compile(r"^[a-fA-F0-9]+$")


def _candidates(h: str) -> list[str]:
    out = []
    n = len(h)
    is_hex = bool(HEX.match(h))
    if h.startswith(("$2a$", "$2b$", "$2y$")):
        return ["bcrypt"]
    if h.startswith("$1$"):
        return ["md5crypt (Unix)"]
    if h.startswith(("$5$",)):
        return ["sha256crypt (Unix)"]
    if h.startswith(("$6$",)):
        return ["sha512crypt (Unix)"]
    if h.startswith("$argon2"):
        return ["Argon2"]
    if is_hex:
        by_len = {
            8: ["CRC-32", "Adler-32"],
            16: ["MySQL<4.1", "CRC-64"],
            32: ["MD5", "MD4", "NTLM", "MD2", "RIPEMD-128"],
            40: ["SHA-1", "RIPEMD-160", "MySQL4.1+ (SHA1)"],
            56: ["SHA-224"],
            64: ["SHA-256", "SHA3-256", "BLAKE2s", "Keccak-256"],
            96: ["SHA-384"],
            128: ["SHA-512", "SHA3-512", "BLAKE2b", "Whirlpool"],
        }
        out = by_len.get(n, [])
    return out


class HashIdentifyModule(BaseModule):
    key = "hash_identify"
    name = "Hash identifier"
    category = Category.INTEL
    subtitle = "Guess the hash algorithm"
    accepts = (InputType.HASH, InputType.TEXT)
    needs_network = False
    description = (
        "Identifies the likely hash algorithm (MD5/SHA-1/SHA-256/NTLM/bcrypt…) "
        "from length and character set. Offline — does not crack or look it up."
    )

    async def run(self, value: str, ctx: RunContext):
        h = value.strip()
        cands = _candidates(h)
        findings = [
            {"label": "Input", "summary": f"{len(h)} chars"},
            {"label": "Character set",
             "summary": "hex" if HEX.match(h) else
             ("crypt/PHC format" if h.startswith("$") else "mixed / non-hex")},
            {"label": "Likely algorithm(s)",
             "summary": cands[0] if cands else "unknown / not a standard hash",
             "values": cands if len(cands) > 1 else None,
             "confidence": "medium" if cands else "info"},
        ]
        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if cands else Confidence.INFO,
            raw={"length": len(h), "candidates": cands},
        )
