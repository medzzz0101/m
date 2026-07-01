"""
modules/file_forensics.py
=========================
Lightweight file forensics for a file YOU provide (CTF / your own files):

  * magic-byte filetype detection (does the extension match the real content?),
  * printable-strings extraction (URLs, keys, hints),
  * "binwalk-lite": scan for KNOWN file signatures appearing AFTER the start —
    i.e. data appended to or embedded in the file,
  * stego LSB peek: pull the least-significant bits of a PNG/BMP's pixels and
    see if they decode to printable ASCII (a common beginner stego trick).

All offline. This is analysis of a file, never exploitation.
"""

from __future__ import annotations

import re
import string

from app.core.base import (
    BaseModule, Category, Confidence, InputType, RunContext,
)

# Magic signatures: prefix bytes -> human filetype.
MAGIC = {
    b"\xff\xd8\xff": "JPEG image",
    b"\x89PNG\r\n\x1a\n": "PNG image",
    b"GIF87a": "GIF image", b"GIF89a": "GIF image",
    b"BM": "BMP image",
    b"%PDF": "PDF document",
    b"PK\x03\x04": "ZIP / Office / APK",
    b"Rar!\x1a\x07": "RAR archive",
    b"\x1f\x8b": "GZIP",
    b"7z\xbc\xaf\x27\x1c": "7-Zip",
    b"\x7fELF": "ELF executable",
    b"MZ": "Windows PE executable",
    b"OggS": "OGG media", b"ID3": "MP3 audio",
    b"\x00\x00\x00\x18ftyp": "MP4 video",
}
# Signatures to hunt for as EMBEDDED/APPENDED data (not at offset 0).
EMBEDDED = {
    b"PK\x03\x04": "ZIP archive", b"\xff\xd8\xff": "JPEG",
    b"\x89PNG\r\n\x1a\n": "PNG", b"%PDF": "PDF", b"Rar!\x1a\x07": "RAR",
    b"7z\xbc\xaf\x27\x1c": "7-Zip",
}
PRINTABLE = set(bytes(string.printable, "ascii")) - set(b"\t\n\r\x0b\x0c")
INTERESTING = re.compile(
    rb"(https?://[^\s\"'<>]{6,}|flag\{[^}]+\}|[A-Za-z0-9]{20,}={0,2})")


def _strings(data: bytes, minlen: int = 5) -> list[str]:
    out, cur = [], bytearray()
    for b in data:
        if b in PRINTABLE:
            cur.append(b)
        else:
            if len(cur) >= minlen:
                out.append(cur.decode("ascii", "ignore"))
            cur = bytearray()
    if len(cur) >= minlen:
        out.append(cur.decode("ascii", "ignore"))
    return out


def _lsb_png(path: str) -> str | None:
    """Extract LSBs of RGB pixels and return any leading printable run."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            px = list(im.getdata())
        bits = []
        for r, g, b in px[:20000]:           # cap work
            bits += [r & 1, g & 1, b & 1]
        # Pack bits -> bytes.
        chars = []
        for i in range(0, len(bits) - 8, 8):
            byte = 0
            for bit in bits[i:i + 8]:
                byte = (byte << 1) | bit
            if 32 <= byte < 127:
                chars.append(chr(byte))
            else:
                break
        text = "".join(chars)
        return text if len(text) >= 4 else None
    except Exception:
        return None


class FileForensicsModule(BaseModule):
    key = "file_forensics"
    name = "File forensics"
    category = Category.IMAGE
    subtitle = "Magic, strings, embedded, LSB"
    accepts = (InputType.FILE, InputType.IMAGE)
    needs_network = False
    description = (
        "Magic-byte filetype, printable strings, binwalk-lite embedded-file scan, "
        "and an LSB stego peek. For CTF and your own files."
    )

    async def run(self, value: str, ctx: RunContext):
        path = ctx.upload_path
        if not path:
            return self.result(error="No uploaded file. Attach a file first.")
        try:
            with open(path, "rb") as fh:
                data = fh.read(2_000_000)  # first 2 MB is plenty for this
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Could not read file: {exc}")

        findings: list[dict] = []

        # 1. Magic filetype.
        ftype = next((v for sig, v in MAGIC.items() if data.startswith(sig)),
                     "unknown / raw data")
        findings.append({"label": "Detected type", "summary": ftype})

        # 2. Embedded/appended signatures (skip offset 0 = the file's own header).
        embedded = []
        for sig, label in EMBEDDED.items():
            idx = data.find(sig, 1)
            if idx > 0:
                embedded.append(f"{label} @ offset {idx}")
        if embedded:
            findings.append({"label": "Embedded/appended data",
                             "summary": f"{len(embedded)} signature(s) — possible "
                                        f"hidden files", "values": embedded,
                             "confidence": "medium"})

        # 3. Interesting strings.
        strings = _strings(data)
        hits = sorted({m.group(0).decode("ascii", "ignore")
                       for m in INTERESTING.finditer(data)})[:30]
        if hits:
            findings.append({"label": "Interesting strings",
                             "values": hits, "confidence": "medium"})
        findings.append({"label": "Strings",
                         "summary": f"{len(strings)} printable runs (≥5 chars)"})

        # 4. LSB stego peek (images only).
        lsb = _lsb_png(path)
        if lsb:
            findings.append({"label": "LSB stego peek",
                             "summary": f"printable LSB data: “{lsb[:60]}”",
                             "confidence": "medium"})

        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if (embedded or hits or lsb)
            else Confidence.INFO,
            raw={"type": ftype, "embedded": embedded, "string_sample": strings[:60]},
        )
