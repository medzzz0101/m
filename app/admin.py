"""admin.py — owner panel backend: manage license keys + see redemptions.

Auth is a secret ADMIN_TOKEN (env). A browser cannot read a hardware/phone ID —
that's blocked for privacy — and mobile IPs rotate, so a token you enter once
(and the browser remembers) is the correct, secure way to prove you're the owner.
The requester's IP is shown for reference only.

Keys live in two places: config.LICENSE_KEYS (env, static) plus a small on-disk
store the owner grows from the panel. Redemptions are logged so you can see usage.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

from . import config

_DATA = Path(__file__).resolve().parent.parent / "data"
_DATA.mkdir(exist_ok=True)
_KEYS_FILE = _DATA / "admin_keys.json"
_LOG_FILE = _DATA / "redemptions.json"

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "limbo-owner-CHANGE-ME")


def check_token(token: str) -> bool:
    return bool(token) and secrets.compare_digest(str(token), ADMIN_TOKEN)


def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save(path: Path, data) -> None:
    try:
        path.write_text(json.dumps(data))
    except Exception:
        pass


def stored_keys() -> dict[str, str]:
    return _load(_KEYS_FILE, {})


def all_keys() -> dict[str, str]:
    """Env-defined keys + owner-generated keys (owner store wins on conflict)."""
    keys = dict(config.license_keys())
    keys.update(stored_keys())
    return keys


def add_key(tier: str) -> str | None:
    if tier not in config.TIER_ORDER:
        return None
    code = f"LIMBO-{tier.upper()}-{secrets.token_hex(3).upper()}"
    keys = stored_keys()
    keys[code] = tier
    _save(_KEYS_FILE, keys)
    return code


def revoke_key(code: str) -> bool:
    keys = stored_keys()
    if code in keys:
        del keys[code]
        _save(_KEYS_FILE, keys)
        return True
    return False


def log_redemption(code: str, tier: str, ip: str) -> None:
    log = _load(_LOG_FILE, [])
    log.append({"code": code, "tier": tier, "ip": ip, "ts": int(time.time())})
    _save(_LOG_FILE, log[-1000:])  # keep last 1000


def redemption_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in _load(_LOG_FILE, []):
        counts[row["code"]] = counts.get(row["code"], 0) + 1
    return counts


def state() -> dict:
    counts = redemption_counts()
    keys = all_keys()
    env_keys = set(config.license_keys())
    rows = [{"code": c, "tier": t, "uses": counts.get(c, 0),
             "source": "env" if c in env_keys else "generated"}
            for c, t in sorted(keys.items(), key=lambda x: x[1])]
    log = _load(_LOG_FILE, [])[-50:][::-1]
    return {"keys": rows, "redemptions": log, "total_redeems": sum(counts.values()),
            "token_is_default": ADMIN_TOKEN == "limbo-owner-CHANGE-ME"}
