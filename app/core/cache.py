"""
core/cache.py
=============
A tiny on-disk cache. OSINT lookups hit rate-limited public APIs, so we never
want to ask the same question twice within a short window. This keeps the UI
snappy and keeps us polite to free services like crt.sh and mempool.space.

Design: one JSON file per cache key (key = sha1 of "namespace:value"). Entries
carry a timestamp; reads past the TTL are treated as misses. Simple, debuggable,
no external dependency.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class DiskCache:
    def __init__(self, root: str | Path, default_ttl: int = 3600):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl

    def _path(self, namespace: str, key: str) -> Path:
        h = hashlib.sha1(f"{namespace}:{key}".encode()).hexdigest()
        return self.root / f"{h}.json"

    def get(self, namespace: str, key: str, ttl: int | None = None) -> Any | None:
        """Return cached value or None if missing/expired."""
        p = self._path(namespace, key)
        if not p.exists():
            return None
        try:
            blob = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        age = time.time() - blob.get("_ts", 0)
        if age > (ttl if ttl is not None else self.default_ttl):
            return None
        return blob.get("value")

    def set(self, namespace: str, key: str, value: Any) -> None:
        p = self._path(namespace, key)
        try:
            p.write_text(json.dumps({"_ts": time.time(), "value": value}))
        except (OSError, TypeError):
            # Caching is best-effort; never let a cache write break a run.
            pass
