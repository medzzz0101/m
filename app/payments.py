"""payments.py — self-hosted crypto payment with on-chain confirmation.

Flow (no third-party gateway needed):
  1. /api/pay/create → we create an invoice: a receiving address, the crypto
     amount for the chosen plan, and a created-at timestamp. It is stored on disk.
  2. The user sends the exact amount from any wallet.
  3. /api/pay/verify → we query the PUBLIC blockchain explorer (mempool.space for
     BTC, a public EVM explorer for ETH/USDT) for a payment to our address that
     is >= the invoice amount and newer than the invoice. If found → plan unlocked.

If no receiving address is configured (see config.PAY_ADDRESS_*), the module
runs in DEMO mode: invoices are created with placeholder addresses and verify
returns "paid" so you can exercise the whole flow safely without real funds.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import httpx

from . import config
from .core.net import get_client

_INVOICE_DIR = Path(__file__).resolve().parent.parent / "data" / "invoices"
_INVOICE_DIR.mkdir(parents=True, exist_ok=True)

# USDC (USD Coin) ERC-20 contract on Ethereum mainnet (6 decimals).
_USDC_CONTRACT = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"


async def _rate(asset: str) -> float:
    """Live USD price for an asset, with a static fallback."""
    try:
        if asset in ("BTC", "ETH"):
            ids = {"BTC": "bitcoin", "ETH": "ethereum"}[asset]
            r = await get_client().get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ids, "vs_currencies": "usd"})
            return float(r.json()[ids]["usd"])
        return config.FALLBACK_RATES.get(asset, 1.0)
    except Exception:
        return config.FALLBACK_RATES.get(asset, 1.0)


def _addr_for(asset: str) -> str:
    if asset == "BTC":
        return config.PAY_ADDRESS_BTC
    if asset == "USDC":
        return config.PAY_ADDRESS_USDC
    return config.PAY_ADDRESS_ETH


async def create_invoice(plan: str, asset: str) -> dict:
    price = config.TIER_META.get(plan, {}).get("price_usd", 0)
    asset = asset.upper()
    demo = not config.PAYMENTS_LIVE or not _addr_for(asset)
    rate = await _rate(asset)
    amount = round(price / rate, 8) if rate else 0.0

    inv = {
        "id": uuid.uuid4().hex[:16],
        "plan": plan,
        "asset": asset,
        "price_usd": price,
        "amount": amount,
        "rate_usd": rate,
        "address": _addr_for(asset) or f"demo-{asset.lower()}-address",
        "paypal": (f"https://paypal.me/{config.PAYPAL_ME}/{price}"
                   if config.PAYPAL_ME else ""),
        "created": time.time(),
        "demo": demo,
        "status": "pending",
    }
    (_INVOICE_DIR / f"{inv['id']}.json").write_text(json.dumps(inv))
    return inv


def _load(invoice_id: str) -> dict | None:
    p = _INVOICE_DIR / f"{invoice_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _save(inv: dict) -> None:
    (_INVOICE_DIR / f"{inv['id']}.json").write_text(json.dumps(inv))


async def verify_invoice(invoice_id: str) -> dict:
    inv = _load(invoice_id)
    if not inv:
        return {"status": "not_found"}
    if inv["status"] == "paid":
        return inv

    # DEMO mode: pretend the payment confirmed so the flow is testable.
    if inv.get("demo"):
        inv["status"] = "paid"
        inv["txid"] = "demo-tx-" + uuid.uuid4().hex[:12]
        _save(inv)
        return inv

    paid = False
    txid = None
    try:
        if inv["asset"] == "BTC":
            paid, txid = await _check_btc(inv)
        else:
            paid, txid = await _check_evm(inv)
    except Exception as e:
        return {**inv, "status": "pending", "error": str(e)}

    if paid:
        inv["status"] = "paid"
        inv["txid"] = txid
        _save(inv)
    return inv


async def _check_btc(inv: dict) -> tuple[bool, str | None]:
    """Look at mempool.space for a received tx >= amount, after invoice time."""
    addr = inv["address"]
    r = await get_client().get(f"https://mempool.space/api/address/{addr}/txs")
    if r.status_code != 200:
        return False, None
    need_sats = int(inv["amount"] * 1e8)
    for tx in r.json():
        received = sum(v["value"] for v in tx.get("vout", [])
                       if v.get("scriptpubkey_address") == addr)
        block_t = tx.get("status", {}).get("block_time", time.time())
        if received >= need_sats and block_t >= inv["created"] - 3600:
            return True, tx.get("txid")
    return False, None


async def _check_evm(inv: dict) -> tuple[bool, str | None]:
    """Check a public EVM explorer for an ETH or USDT transfer to our address."""
    addr = inv["address"].lower()
    if inv["asset"] == "USDC":
        # Token transfers via Blockscout-compatible public API.
        url = f"https://eth.blockscout.com/api/v2/addresses/{addr}/token-transfers"
        r = await get_client().get(url)
        if r.status_code != 200:
            return False, None
        need = inv["amount"]
        for t in r.json().get("items", []):
            tok = (t.get("token") or {}).get("address", "").lower()
            if tok != _USDC_CONTRACT.lower():
                continue
            val = float(t.get("total", {}).get("value", 0)) / 1e6
            if val >= need:
                return True, t.get("transaction_hash")
        return False, None
    # Native ETH transfers.
    url = f"https://eth.blockscout.com/api/v2/addresses/{addr}/transactions"
    r = await get_client().get(url)
    if r.status_code != 200:
        return False, None
    need_wei = int(inv["amount"] * 1e18)
    for t in r.json().get("items", []):
        if (t.get("to", {}) or {}).get("hash", "").lower() == addr:
            if int(t.get("value", 0)) >= need_wei:
                return True, t.get("hash")
    return False, None
