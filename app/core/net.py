"""net.py — one shared, correctly-configured async HTTP client.

This cloud environment has NO direct outbound network: everything must egress
through an HTTPS CONNECT proxy (HTTPS_PROXY), and TLS must be verified against
the proxy's CA bundle. Getting this right once, here, means every module just
calls `get_client()` and works. Modules must NEVER create their own client.
"""
from __future__ import annotations

import os

import httpx

# The proxy + CA come from the environment the container was started with.
_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
_CA = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or True

# A browser-ish UA — many public endpoints reject the default python-httpx UA.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Return the process-wide AsyncClient, creating it on first use."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            proxy=_PROXY,
            verify=_CA,
            follow_redirects=True,          # RDAP/urlscan/etc. redirect a lot
            timeout=httpx.Timeout(12.0, connect=8.0),
            headers={"User-Agent": _UA, "Accept": "*/*"},
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def tls_peercert(host: str, port: int = 443, timeout: float = 8.0) -> bytes | None:
    """Fetch a host's live TLS certificate (DER) — proxy-aware.

    A plain `socket.create_connection` fails in egress-restricted environments
    where the only way out is the HTTPS CONNECT proxy. This opens a CONNECT
    tunnel through $HTTPS_PROXY when present, otherwise connects directly, then
    does the TLS handshake and returns the peer certificate. Blocking — call it
    from a thread (e.g. asyncio.to_thread / run_in_executor).
    """
    import socket
    import ssl
    from urllib.parse import urlparse

    sock = _open_tunnel(host, port, timeout)
    ctxs = ssl.create_default_context()
    ctxs.check_hostname = False
    ctxs.verify_mode = ssl.CERT_NONE
    with ctxs.wrap_socket(sock, server_hostname=host) as ss:
        return ss.getpeercert(binary_form=True)


def tls_supports(host: str, min_ver, max_ver, port: int = 443, timeout: float = 6.0) -> bool:
    """True if host:port completes a TLS handshake pinned to [min_ver, max_ver]."""
    import ssl
    try:
        sock = _open_tunnel(host, port, timeout)
        ctxs = ssl.create_default_context()
        ctxs.check_hostname = False
        ctxs.verify_mode = ssl.CERT_NONE
        ctxs.minimum_version = min_ver
        ctxs.maximum_version = max_ver
        with ctxs.wrap_socket(sock, server_hostname=host):
            return True
    except Exception:
        return False


def _open_tunnel(host: str, port: int, timeout: float):
    """Return a raw socket connected to host:port, via the proxy if configured."""
    import socket
    from urllib.parse import urlparse
    if _PROXY:
        u = urlparse(_PROXY)
        s = socket.create_connection((u.hostname, u.port or 8080), timeout=timeout)
        s.settimeout(timeout)
        s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(1024)
            if not chunk:
                break
            resp += chunk
        if b" 200 " not in resp.split(b"\r\n", 1)[0]:
            s.close()
            raise ConnectionError(f"proxy refused CONNECT to {host}:{port}")
        return s
    return socket.create_connection((host, port), timeout=timeout)
