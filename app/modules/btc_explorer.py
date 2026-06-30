"""
modules/btc_explorer.py
=======================
Bitcoin on-chain lookup (basic, Phase 1 — chain-following / clustering come in
Phase 3). Uses the PUBLIC mempool.space / Blockstream Esplora API (no key).

Handles either a BTC address or a transaction id:
  * address: balance, total received/sent, tx count, recent transactions
  * tx      : inputs, outputs, fee, confirmation status

GUARDRAIL: on-chain ledger facts ONLY. We never attempt to attribute an
address to a real person — Bitcoin's ledger is public, identities are not.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json

API = "https://mempool.space/api"


def _sats(n: int) -> str:
    """Render satoshis as BTC for humans."""
    return f"{n/1e8:.8f} BTC"


class BtcExplorerModule(BaseModule):
    key = "btc_explorer"
    name = "Bitcoin explorer"
    category = Category.BLOCKCHAIN
    subtitle = "Address / tx — balance & history"
    accepts = (InputType.BTC_ADDRESS, InputType.HASH)
    needs_network = True
    description = (
        "Public Bitcoin ledger lookup via mempool.space: address balance, "
        "totals, and recent transactions, or a single transaction's I/O. "
        "On-chain facts only — no real-person attribution."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()

        # A 64-hex string routed here is a txid; otherwise treat as an address.
        is_txid = len(v) == 64 and all(c in "0123456789abcdefABCDEF" for c in v)
        if is_txid:
            return await self._tx(v, ctx)
        return await self._address(v, ctx)

    # ----------------------------------------------------------------------
    async def _address(self, addr: str, ctx: RunContext):
        try:
            info = await fetch_json(ctx, f"{API}/address/{addr}",
                                    ttl=300, namespace="btc")
            txs = await fetch_json(ctx, f"{API}/address/{addr}/txs",
                                   ttl=300, namespace="btc")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Address lookup failed: {exc}",
                               source_url=f"https://mempool.space/address/{addr}")

        chain = info.get("chain_stats", {})
        funded = chain.get("funded_txo_sum", 0)
        spent = chain.get("spent_txo_sum", 0)
        balance = funded - spent
        tx_count = chain.get("tx_count", 0)

        findings = [
            {"label": "Balance", "summary": _sats(balance)},
            {"label": "Total received", "summary": _sats(funded)},
            {"label": "Total sent", "summary": _sats(spent)},
            {"label": "Transactions", "summary": str(tx_count)},
        ]

        nodes = [GraphNode("btc_address", addr,
                           props={"balance_sat": balance, "tx_count": tx_count})]
        edges: list[GraphEdge] = []

        # Recent tx ids -> tx nodes (lightweight; deep follow is Phase 3).
        recent = []
        for tx in (txs or [])[:10]:
            txid = tx.get("txid")
            if not txid:
                continue
            recent.append(txid)
            nodes.append(GraphNode("tx", txid, label=txid[:12] + "…"))
            edges.append(GraphEdge(f"btc_address:{addr}", f"tx:{txid}", "funds_flow_to"))
        if recent:
            findings.append({"label": "Recent transactions", "values": recent})

        return self.result(
            findings=findings,
            confidence=Confidence.HIGH,
            source_url=f"https://mempool.space/address/{addr}",
            raw={"info": info, "tx_sample": (txs or [])[:10]},
            nodes=nodes,
            edges=edges,
        )

    # ----------------------------------------------------------------------
    async def _tx(self, txid: str, ctx: RunContext):
        try:
            tx = await fetch_json(ctx, f"{API}/tx/{txid}", ttl=600, namespace="btc")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Transaction lookup failed: {exc}",
                               source_url=f"https://mempool.space/tx/{txid}")

        vin = tx.get("vin", [])
        vout = tx.get("vout", [])
        fee = tx.get("fee", 0)
        out_total = sum(o.get("value", 0) for o in vout)

        in_addrs = [i.get("prevout", {}).get("scriptpubkey_address")
                    for i in vin if i.get("prevout")]
        out_addrs = [(o.get("scriptpubkey_address"), o.get("value", 0)) for o in vout]

        findings = [
            {"label": "Inputs", "summary": f"{len(vin)} input(s)",
             "values": [a for a in in_addrs if a]},
            {"label": "Outputs", "summary": f"{len(vout)} output(s)",
             "values": [f"{a} — {_sats(val)}" for a, val in out_addrs if a]},
            {"label": "Output total", "summary": _sats(out_total)},
            {"label": "Fee", "summary": _sats(fee)},
            {"label": "Confirmed",
             "summary": "yes" if tx.get("status", {}).get("confirmed") else "pending"},
        ]

        nodes = [GraphNode("tx", txid, label=txid[:12] + "…")]
        edges: list[GraphEdge] = []
        for a in in_addrs:
            if a:
                nodes.append(GraphNode("btc_address", a))
                edges.append(GraphEdge(f"btc_address:{a}", f"tx:{txid}", "funds_flow_to"))
        for a, val in out_addrs:
            if a:
                nodes.append(GraphNode("btc_address", a))
                edges.append(GraphEdge(f"tx:{txid}", f"btc_address:{a}", "funds_flow_to",
                                       props={"value_sat": val}))

        return self.result(
            findings=findings,
            confidence=Confidence.HIGH,
            source_url=f"https://mempool.space/tx/{txid}",
            raw=tx,
            nodes=nodes,
            edges=edges,
        )
