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
# Set these in .env to receive real payments. Left blank → the console runs in
# DEMO mode (it shows the flow and unlocks instantly without a real charge).
PAY_ADDRESS_BTC  = os.environ.get("PAY_ADDRESS_BTC", "")
PAY_ADDRESS_ETH  = os.environ.get("PAY_ADDRESS_ETH", "")   # also receives USDT (ERC-20)
PAYPAL_ME        = os.environ.get("PAYPAL_ME", "")          # e.g. "yourname" for paypal.me/yourname

# Rough fiat→crypto reference rates are fetched live; these are fallbacks only.
FALLBACK_RATES = {"BTC": 65000.0, "ETH": 3400.0, "USDT": 1.0}

PAYMENTS_LIVE = bool(PAY_ADDRESS_BTC or PAY_ADDRESS_ETH or PAYPAL_ME)
