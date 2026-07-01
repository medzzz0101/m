"""
modules/port_services.py
========================
The one ACTIVE module. It makes real TCP connections to a target to see which
common ports are open and grabs any banner the service sends on connect. Because
this actually touches the target, it is gated:

    requires_authorized_target = True

…so the orchestrator refuses to run it unless the user has ticked the
scope-confirmation box ("this is mine / I'm authorised"). Everything else in the
suite is passive; this is the deliberate exception, fenced off behind consent.

No exploitation, no brute force — a connect() and a read(), nothing more.
"""

from __future__ import annotations

import asyncio
import os
import socket
from urllib.parse import urlparse

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import resolve_ip

# Common ports and the service usually behind them.
PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP",
    110: "POP3", 143: "IMAP", 443: "HTTPS", 445: "SMB", 587: "SMTP-sub",
    993: "IMAPS", 995: "POP3S", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    6379: "Redis", 8080: "HTTP-alt", 8443: "HTTPS-alt", 27017: "MongoDB",
}


HTTP_PORTS = {80, 8080, 591, 8000, 8008}
TLS_PORTS = {443, 8443, 993, 995, 465}


def _connect(host: str, port: int, timeout: float):
    """Open a raw socket to host:port, via the egress CONNECT proxy if set.
    Returns the socket, or None if even CONNECT fails."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        p = urlparse(proxy)
        s = socket.create_connection((p.hostname, p.port), timeout=timeout)
        s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\n"
                  f"Host: {host}:{port}\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(256)
            if not chunk:
                s.close(); return None
            buf += chunk
        if b" 200 " not in buf.split(b"\r\n")[0]:
            s.close(); return None
        return s
    return socket.create_connection((host, port), timeout=timeout)


def _probe_port(host: str, port: int, timeout: float = 5.0) -> dict | None:
    """EVIDENCE-BASED open-port check. Because our egress proxy returns CONNECT
    200 for every port (open or not), we must PROVE the service is live rather
    than trust the connect: we require a banner, a valid HTTP reply, or a TLS
    handshake. This under-reports silent services but never false-positives —
    the honest trade-off when scanning from behind a CONNECT proxy."""
    try:
        s = _connect(host, port, timeout)
        if s is None:
            return None

        # 1. Banner-first services (SSH/FTP/SMTP/POP/IMAP/MySQL…) announce themselves.
        s.settimeout(2.5)
        banner = b""
        try:
            banner = s.recv(160)
        except Exception:
            pass
        if banner.strip():
            s.close()
            return {"port": port, "banner": banner.decode("latin-1", "ignore").strip(),
                    "evidence": "banner"}

        # 2. HTTP ports: a HEAD must yield an HTTP status line.
        if port in HTTP_PORTS:
            try:
                s.sendall(f"HEAD / HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
                resp = s.recv(160)
                s.close()
                if resp.startswith(b"HTTP/"):
                    line = resp.split(b"\r\n")[0].decode("latin-1", "ignore")
                    return {"port": port, "banner": line, "evidence": "http"}
                return None
            except Exception:
                s.close(); return None

        # 3. TLS ports: a successful handshake proves it's live.
        if port in TLS_PORTS:
            try:
                import ssl
                c = ssl.create_default_context()
                c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
                ss = c.wrap_socket(s, server_hostname=host)
                cipher = ss.cipher()
                ss.close()
                return {"port": port, "banner": f"TLS {cipher[1] if cipher else ''}",
                        "evidence": "tls"}
            except Exception:
                try: s.close()
                except Exception: pass
                return None

        # 4. No evidence -> treat as closed/filtered (avoids proxy false positives).
        s.close()
        return None
    except Exception:
        return None


class PortServicesModule(BaseModule):
    key = "port_services"
    name = "Port & service scan"
    category = Category.INFRASTRUCTURE
    subtitle = "ACTIVE — authorized targets only"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    requires_authorized_target = True   # <-- gated behind the scope confirmation
    description = (
        "ACTIVE TCP connect-scan of common ports with banner grab. Touches the "
        "target directly, so it only runs after you confirm authorization. Recon "
        "only — no exploitation."
    )

    async def run(self, value: str, ctx: RunContext):
        host = value.strip()
        ip = await resolve_ip(host)
        if not ip:
            return self.result(error=f"Could not resolve '{host}'.")

        loop = asyncio.get_running_loop()
        # Probe all ports concurrently (bounded by the thread pool).
        results = await asyncio.gather(
            *(loop.run_in_executor(None, _probe_port, host, port)
              for port in PORTS))
        open_ports = [r for r in results if r]

        findings = [{
            "label": "Scope",
            "summary": "Authorized active scan — TCP connect + banner only.",
            "confidence": "info",
        }, {
            "label": "Method",
            "summary": "Evidence-based (banner / HTTP / TLS). Silent services may "
                       "be under-reported — this avoids false positives behind the "
                       "environment's CONNECT proxy.",
            "confidence": "info",
        }, {
            "label": "Open ports",
            "summary": f"{len(open_ports)} confirmed of {len(PORTS)} probed",
            "values": [f"{r['port']}/{PORTS[r['port']]} [{r.get('evidence','?')}]"
                       + (f"  «{r['banner'][:36]}»" if r['banner'] else "")
                       for r in sorted(open_ports, key=lambda x: x['port'])]
                      or ["none confirmed open"],
        }]

        nodes = [GraphNode("ip", ip)]
        edges: list[GraphEdge] = []
        for r in open_ports:
            svc = f"{ip}:{r['port']}"
            nodes.append(GraphNode("service", svc,
                                   label=f"{PORTS[r['port']]} :{r['port']}",
                                   props={"banner": r["banner"]}))
            edges.append(GraphEdge(f"ip:{ip}", f"service:{svc}", "exposes"))

        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if open_ports else Confidence.INFO,
            raw={"open": open_ports}, nodes=nodes, edges=edges,
        )
