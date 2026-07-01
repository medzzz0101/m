"""
modules/eth_explorer.py
=======================
EVM (Ethereum) on-chain lookup for an address or transaction. Works with NO key
via Blockscout's public API, and uses an Etherscan key from .env if you provide
one (unlocks richer/higher-rate queries).

Like the Bitcoin module: on-chain ledger facts ONLY — balances, tx counts,
transfers. No attempt to tie an address to a real person.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json

BLOCKSCOUT = "https://eth.blockscout.com/api"
ETHERSCAN = "https://api.etherscan.io/api"


def _eth(wei: int) -> str:
    return f"{wei/1e18:.6f} ETH"


class EthExplorerModule(BaseModule):
    key = "eth_explorer"
    name = "Ethereum explorer"
    category = Category.BLOCKCHAIN
    subtitle = "EVM address / tx (no key)"
    accepts = (InputType.ETH_ADDRESS, InputType.HASH)
    needs_network = True
    description = (
        "Public EVM on-chain lookup (Blockscout, no key; Etherscan key optional): "
        "balance, tx count and recent transfers for an address, or a transaction. "
        "On-chain facts only — no real-person attribution."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        key = ctx.config.get("ETHERSCAN_API_KEY", "").strip()
        base = ETHERSCAN if key else BLOCKSCOUT
        suffix = f"&apikey={key}" if key else ""
        source = "Etherscan" if key else "Blockscout"

        # A 66-char 0x hash is a txid; a 42-char 0x is an address.
        if v.startswith("0x") and len(v) == 66:
            return await self._tx(v, ctx, base, suffix, source)
        return await self._address(v, ctx, base, suffix, source)

    async def _address(self, addr, ctx, base, suffix, source):
        try:
            bal = await fetch_json(
                ctx, f"{base}?module=account&action=balance&address={addr}"
                     f"&tag=latest{suffix}", ttl=120, namespace="eth")
            txs = await fetch_json(
                ctx, f"{base}?module=account&action=txlist&address={addr}"
                     f"&page=1&offset=10&sort=desc{suffix}", ttl=120, namespace="eth")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"{source} lookup failed: {exc}",
                               source_url=f"https://etherscan.io/address/{addr}")

        wei = int(bal.get("result", 0) or 0)
        tx_list = txs.get("result", []) if isinstance(txs.get("result"), list) else []

        findings = [
            {"label": "Balance", "summary": _eth(wei)},
            {"label": "Recent transfers", "summary": f"{len(tx_list)} shown"},
        ]
        recent = []
        nodes = [GraphNode("eth_address", addr.lower(), props={"balance_wei": wei})]
        edges: list[GraphEdge] = []
        for t in tx_list[:10]:
            h = t.get("hash", "")
            frm, to = (t.get("from") or "").lower(), (t.get("to") or "").lower()
            val = int(t.get("value", 0) or 0)
            recent.append(f"{h[:12]}… {_eth(val)}  {frm[:8]}→{to[:8]}")
            if to:
                nodes.append(GraphNode("eth_address", to))
                edges.append(GraphEdge(f"eth_address:{frm or addr.lower()}",
                                       f"eth_address:{to}", "funds_flow_to",
                                       props={"value_wei": val}))
        if recent:
            findings.append({"label": "Transactions", "values": recent})

        return self.result(
            findings=findings, confidence=Confidence.HIGH,
            source_url=f"https://etherscan.io/address/{addr}",
            raw={"balance_wei": wei, "tx_sample": tx_list[:10], "source": source},
            nodes=nodes, edges=edges,
        )

    async def _tx(self, txid, ctx, base, suffix, source):
        try:
            tx = await fetch_json(
                ctx, f"{base}?module=proxy&action=eth_getTransactionByHash"
                     f"&txhash={txid}{suffix}", ttl=600, namespace="eth")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"{source} tx lookup failed: {exc}",
                               source_url=f"https://etherscan.io/tx/{txid}")
        r = tx.get("result") or {}
        if not r:
            return self.result(error="Transaction not found.",
                               source_url=f"https://etherscan.io/tx/{txid}")
        frm, to = (r.get("from") or "").lower(), (r.get("to") or "").lower()
        val = int(r.get("value", "0x0"), 16) if r.get("value") else 0
        findings = [
            {"label": "From", "summary": frm or "—"},
            {"label": "To", "summary": to or "(contract creation)"},
            {"label": "Value", "summary": _eth(val)},
        ]
        nodes = [GraphNode("tx", txid, label=txid[:12] + "…")]
        edges = []
        for a in (frm, to):
            if a:
                nodes.append(GraphNode("eth_address", a))
        if frm and to:
            edges.append(GraphEdge(f"eth_address:{frm}", f"eth_address:{to}",
                                   "funds_flow_to", props={"value_wei": val, "tx": txid}))
        return self.result(findings=findings, confidence=Confidence.HIGH,
                           source_url=f"https://etherscan.io/tx/{txid}",
                           raw=r, nodes=nodes, edges=edges)
