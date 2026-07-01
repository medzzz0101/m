"""
modules/tls_certs.py
====================
Inspect the LIVE TLS certificate a domain serves on :443 — issuer, validity
window, and the Subject Alternative Names (SANs). SANs are gold for correlation:
one cert often covers many related domains, so its SAN list pivots you straight
to an organisation's other properties.

We open a real TLS connection (through the egress CONNECT proxy if present) and
read the peer certificate with Python's ssl module. No third-party service.
"""

from __future__ import annotations

import asyncio
import os
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)


def _proxy_socket(host: str, port: int, timeout: float) -> socket.socket:
    """TCP socket to host:port, via HTTPS_PROXY CONNECT when one is configured
    (this container has no direct egress), else a direct connection."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        p = urlparse(proxy)
        s = socket.create_connection((p.hostname, p.port), timeout=timeout)
        s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(1024)
            if not chunk:
                raise RuntimeError("proxy closed during CONNECT")
            buf += chunk
        if b" 200 " not in buf.split(b"\r\n")[0]:
            raise RuntimeError(f"proxy refused CONNECT: {buf.splitlines()[0]!r}")
        return s
    return socket.create_connection((host, port), timeout=timeout)


def _get_cert(host: str, port: int = 443, timeout: float = 10) -> dict:
    """Blocking TLS handshake -> parsed certificate fields.

    We deliberately DON'T validate the chain (self-signed / expired certs are
    themselves findings we want to report). Under CERT_NONE Python's
    getpeercert() returns {}, so we grab the DER bytes and parse them with the
    `cryptography` library (available as a paramiko dependency)."""
    raw = _proxy_socket(host, port, timeout)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with ctx.wrap_socket(raw, server_hostname=host) as ss:
        der = ss.getpeercert(binary_form=True)
    return _parse_der(der)


def _parse_der(der: bytes) -> dict:
    """Parse a DER certificate into a flat dict of the fields we surface."""
    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID, NameOID

    cert = x509.load_der_x509_certificate(der)

    def _name(name, oid):
        vals = name.get_attributes_for_oid(oid)
        return vals[0].value if vals else None

    sans: list[str] = []
    try:
        ext = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        sans = ext.value.get_values_for_type(x509.DNSName)
    except Exception:
        pass

    return {
        "subject_cn": _name(cert.subject, NameOID.COMMON_NAME),
        "issuer_org": _name(cert.issuer, NameOID.ORGANIZATION_NAME),
        "issuer_cn": _name(cert.issuer, NameOID.COMMON_NAME),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "expired": cert.not_valid_after_utc < datetime.now(timezone.utc),
        "serial": format(cert.serial_number, "x"),
        "sans": sans,
    }


class TlsCertsModule(BaseModule):
    key = "tls_certs"
    name = "TLS certificate"
    category = Category.INFRASTRUCTURE
    subtitle = "Issuer, validity, SAN pivot"
    accepts = (InputType.DOMAIN, InputType.IP)
    needs_network = True
    description = (
        "Reads the live TLS certificate (issuer, validity window, Subject "
        "Alternative Names) and pivots via SANs to related domains."
    )

    async def run(self, value: str, ctx: RunContext):
        host = value.strip().lower()
        loop = asyncio.get_running_loop()
        try:
            cert = await loop.run_in_executor(None, _get_cert, host)
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"TLS handshake failed: {exc}",
                               source_url=f"https://{host}")

        subject_cn = cert.get("subject_cn") or host
        issuer = cert.get("issuer_org") or cert.get("issuer_cn") or "—"
        sans = cert.get("sans", [])
        expired = cert.get("expired")

        findings = [
            {"label": "Subject (CN)", "summary": subject_cn},
            {"label": "Issuer", "summary": issuer},
            {"label": "Valid from", "summary": cert.get("not_before", "—")},
            {"label": "Valid until", "summary": cert.get("not_after", "—"),
             "confidence": "low" if expired else "info"},
            {"label": "Status",
             "summary": "EXPIRED" if expired else "currently valid",
             "confidence": "low" if expired else "high"},
        ]
        if sans:
            findings.append({"label": f"SANs ({len(sans)})", "values": sans})

        # SAN pivot: each distinct name becomes a related domain node.
        nodes = [GraphNode("domain", host)]
        edges: list[GraphEdge] = []
        cert_id = f"{issuer}|{subject_cn}"
        nodes.append(GraphNode("cert", cert_id, label=subject_cn))
        edges.append(GraphEdge(f"domain:{host}", f"cert:{cert_id}", "issued_cert"))
        for san in sans:
            san = san.lstrip("*.").lower()
            if san and san != host:
                nodes.append(GraphNode("domain", san))
                edges.append(GraphEdge(f"cert:{cert_id}", f"domain:{san}",
                                       "same_owner", props={"via": "SAN"}))

        return self.result(
            findings=findings, confidence=Confidence.HIGH,
            source_url=f"https://crt.sh/?q={host}",
            raw={k: str(v) for k, v in cert.items()},
            nodes=nodes, edges=edges,
        )
