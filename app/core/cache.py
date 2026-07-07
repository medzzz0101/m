"""cache.py — a tiny disk cache so repeated runs are fast and kind to APIs.

Keyed by module id + target, values are JSON blobs with a stored timestamp.
Entries older than their TTL are ignored. This is intentionally minimal — no
eviction thread, no locking beyond the filesystem; good enough for a self-hosted
single-user-ish console and easy to read.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional


class DiskCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        h = hashlib.sha256(key.encode()).hexdigest()[:24]
        return self.root / f"{h}.json"

    def get(self, key: str, ttl: float) -> Optional[Any]:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            blob = json.loads(p.read_text())
            if time.time() - blob["_ts"] > ttl:
                return None
            return blob["data"]
        except Exception:
            return None

    def set(self, key: str, data: Any) -> None:
        try:
            self._path(key).write_text(json.dumps({"_ts": time.time(), "data": data}))
        except Exception:
            pass  # a cache write failing must never break a run
