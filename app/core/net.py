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
