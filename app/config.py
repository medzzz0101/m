"""config.py — plans, tiers and payment settings in one readable place."""
from __future__ import annotations

import os

# Tier order from least to most capable. A user on tier N can run any module
# whose tier index is <= N. Modules declare their tier in their class.
TIER_ORDER = ["base", "premium", "elite", "master"]

TIER_META = {
    "base":    {"name": "Base",    "price_usd": 0,   "blurb": "Core public-data OSINT, free forever."},
    "premium": {"name": "Premium", "price_usd": 9,   "blurb": "Deeper social, infra & image modules."},
    "elite":   {"name": "Elite",   "price_usd": 29,  "blurb": "Threat context, forensics, identity proofs."},
    "master":  {"name": "Master",  "price_usd": 79,  "blurb": "Everything, max concurrency, priority."},
}

def tier_index(tier: str) -> int:
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0

# --- Payment: self-hosted crypto (on-chain confirmation) + PayPal -----------
# Receiving addresses (public by nature). Env vars override these defaults, so
# you can rotate them on the host without touching code.
PAY_ADDRESS_BTC  = os.environ.get("PAY_ADDRESS_BTC",  "bc1q6cp3n3dsss42cqajm53fftgq566vryzqc2g8h7")
PAY_ADDRESS_ETH  = os.environ.get("PAY_ADDRESS_ETH",  "0x70CE2a516651d7044f1233515963423caB68104b")  # ETH + USDC (ERC-20)
PAY_ADDRESS_USDC = os.environ.get("PAY_ADDRESS_USDC", "0x70CE2a516651d7044f1233515963423caB68104b")
PAYPAL_ME        = os.environ.get("PAYPAL_ME", "")          # e.g. "yourname" for paypal.me/yourname

# Rough fiat→crypto reference rates are fetched live; these are fallbacks only.
FALLBACK_RATES = {"BTC": 65000.0, "ETH": 3400.0, "USDC": 1.0}

PAYMENTS_LIVE = bool(PAY_ADDRESS_BTC or PAY_ADDRESS_ETH or PAYPAL_ME)

# --- License keys: owner-issued codes that unlock a tier, reusable forever ----
# Format in env:  LICENSE_KEYS="CODE1:master,CODE2:elite,CODE3:premium"
# Each code unlocks its tier for anyone who enters it, with unlimited uses.
# A default set is seeded so you have keys to hand out immediately — CHANGE THEM.
_DEFAULT_KEYS = "LIMBO-MASTER-9F3K:master,LIMBO-ELITE-7Q2X:elite,LIMBO-PREMIUM-4T8M:premium"

def license_keys() -> dict[str, str]:
    raw = os.environ.get("LICENSE_KEYS", _DEFAULT_KEYS)
    out: dict[str, str] = {}
    for part in raw.split(","):
        if ":" in part:
            code, tier = part.split(":", 1)
            code = code.strip()
            tier = tier.strip()
            if code and tier in TIER_ORDER:
                out[code] = tier
    return out
