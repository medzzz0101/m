"""
modules/tls_scan.py
===================
Which TLS protocol versions does a host accept? Legacy protocols (SSLv3, TLS 1.0,
TLS 1.1) are deprecated and a compliance/security red flag; TLS 1.3 is the modern
baseline. We attempt a handshake forcing each version and report what's accepted,
plus the negotiated cipher for a default connection.

Handshakes go through the egress CONNECT proxy. Pure diagnostics — connect and
read the negotiated parameters, nothing more.
"""

from __future__ import annotations

import asyncio
import os
import socket
import ssl
from urllib.parse import urlparse

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)

# label -> (min, max) TLSVersion to force a single-version handshake.
VERSIONS = [
    ("TLS 1.0", ssl.TLSVersion.TLSv1),
    ("TLS 1.1", ssl.TLSVersion.TLSv1_1),
    ("TLS 1.2", ssl.TLSVersion.TLSv1_2),
    ("TLS 1.3", ssl.TLSVersion.TLSv1_3),
]
LEGACY = {"TLS 1.0", "TLS 1.1"}


def _sock(host, port, timeout):
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        p = urlparse(proxy)
        s = socket.create_connection((p.hostname, p.port), timeout=timeout)
        s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            c = s.recv(256)
            if not c:
                raise RuntimeError("proxy closed")
            buf += c
        if b" 200 " not in buf.split(b"\r\n")[0]:
            raise RuntimeError("proxy refused CONNECT")
        return s
    return socket.create_connection((host, port), timeout=timeout)


def _try_version(host, version) -> bool:
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = version
        ctx.maximum_version = version
        s = _sock(host, 443, 8)
        with ctx.wrap_socket(s, server_hostname=host):
            return True
    except Exception:
        return False


def _default_cipher(host):
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        s = _sock(host, 443, 8)
        with ctx.wrap_socket(s, server_hostname=host) as ss:
            c = ss.cipher()
            return {"version": ss.version(), "cipher": c[0] if c else "?"}
    except Exception:
        return {}


class TlsScanModule(BaseModule):
    key = "tls_scan"
    name = "TLS protocol scan"
    category = Category.INFRASTRUCTURE
    subtitle = "Which TLS versions accepted"
    accepts = (InputType.DOMAIN, InputType.IP)
    needs_network = True
    description = (
        "Tests which TLS versions a host accepts (flags legacy TLS 1.0/1.1) and "
        "reports the negotiated cipher. Handshake diagnostics only."
    )

    async def run(self, value: str, ctx: RunContext):
        host = value.strip().lower()
        loop = asyncio.get_running_loop()
        # Sequential — the CONNECT proxy is flaky under many parallel TLS dials.
        accepted = []
        for label, ver in VERSIONS:
            if await loop.run_in_executor(None, _try_version, host, ver):
                accepted.append(label)
        default = await loop.run_in_executor(None, _default_cipher, host)

        if not accepted and not default:
            return self.result(error="No TLS on :443 (or host unreachable).",
                               source_url=f"https://{host}")

        legacy = [a for a in accepted if a in LEGACY]
        findings = [
            {"label": "Accepted versions", "values": accepted or ["none negotiated"],
             "confidence": "info"},
            {"label": "Default negotiated",
             "summary": f"{default.get('version','?')} · {default.get('cipher','?')}"},
            {"label": "TLS 1.3", "summary": "supported" if "TLS 1.3" in accepted
             else "NOT supported"},
        ]
        if legacy:
            findings.append({"label": "⚠ Legacy protocols",
                             "summary": f"{', '.join(legacy)} accepted — deprecated/insecure",
                             "confidence": "medium"})
        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if legacy else Confidence.HIGH,
            source_url=f"https://www.ssllabs.com/ssltest/analyze.html?d={host}",
            raw={"accepted": accepted, "default": default, "legacy": legacy},
            nodes=[GraphNode("domain", host)],
        )
