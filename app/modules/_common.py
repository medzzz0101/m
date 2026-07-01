"""
modules/_common.py
==================
Small shared helpers used by many modules. Prefixed with "_" so the registry's
auto-discovery walk skips it (it holds no modules of its own).
"""

from __future__ import annotations

import asyncio
import socket
from urllib.parse import urlparse
from typing import Any

import httpx


async def resolve_ip(host: str) -> str | None:
    """Resolve a hostname to its first IPv4 address (off the event loop).
    Returns the input unchanged if it already looks like an IP."""
    # Quick check: already an IP?
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        pass
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.run_in_executor(
            None, lambda: socket.getaddrinfo(host, None, socket.AF_INET))
        return infos[0][4][0] if infos else None
    except Exception:
        return None


def host_of(url: str) -> str:
    """Best-effort hostname extraction for the per-host rate limiter."""
    try:
        return urlparse(url).hostname or url
    except Exception:
        return url


async def fetch_json(
    ctx, url: str, *, ttl: int = 3600, namespace: str = "json", **kwargs
) -> Any:
    """GET a URL, parse JSON, with disk caching + per-host rate limiting.

    `ctx` is the RunContext (gives us ctx.http and ctx.cache). This is the
    one-liner most network modules call. Raises httpx errors for non-2xx so the
    caller can decide how to present failures.
    """
    cached = ctx.cache.get(namespace, url, ttl=ttl)
    if cached is not None:
        return cached
    limiter = ctx.extra.get("rate_limiter")
    host = host_of(url)
    if limiter is not None:
        async with limiter.slot(host):
            resp = await ctx.http.get(url, **kwargs)
    else:
        resp = await ctx.http.get(url, **kwargs)
    resp.raise_for_status()
    data = resp.json()
    ctx.cache.set(namespace, url, data)
    return data


async def fetch_text(
    ctx, url: str, *, ttl: int = 3600, namespace: str = "text", **kwargs
) -> str:
    """Same as fetch_json but returns raw text (HTML/cert PEM/etc.)."""
    cached = ctx.cache.get(namespace, url, ttl=ttl)
    if cached is not None:
        return cached
    limiter = ctx.extra.get("rate_limiter")
    host = host_of(url)
    if limiter is not None:
        async with limiter.slot(host):
            resp = await ctx.http.get(url, **kwargs)
    else:
        resp = await ctx.http.get(url, **kwargs)
    resp.raise_for_status()
    text = resp.text
    ctx.cache.set(namespace, url, text)
    return text
