"""
modules/btc_trace.py
====================
Advanced Bitcoin analysis for an address:

  * FOLLOW THE CHAIN — trace where funds flowed by walking outputs a few hops
    forward, building a funds-flow subgraph.
  * COMMON-INPUT-OWNERSHIP CLUSTERING — the classic heuristic: when several
    addresses are spent together as inputs to one transaction, they're very
    likely controlled by the same entity. We surface those co-spent clusters.

Everything is derived from the PUBLIC ledger via mempool.space (no key). This is
on-chain analysis only — it links addresses by ledger behaviour, never to a real
person.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json

API = "https://mempool.space/api"


def _btc(sats: int) -> str:
    return f"{sats/1e8:.8f} BTC"


class BtcTraceModule(BaseModule):
    key = "btc_trace"
    name = "Bitcoin trace & cluster"
    category = Category.BLOCKCHAIN
    subtitle = "Chain-follow + input clustering"
    accepts = (InputType.BTC_ADDRESS,)
    needs_network = True
    description = (
        "Follows funds forward a few hops and applies common-input-ownership "
        "clustering (co-spent inputs = same wallet). Public ledger only — links "
        "addresses by on-chain behaviour, never to a person."
    )

    async def run(self, value: str, ctx: RunContext):
        addr = value.strip()
        try:
            txs = await fetch_json(ctx, f"{API}/address/{addr}/txs", ttl=300,
                                   namespace="btc")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Address lookup failed: {exc}",
                               source_url=f"https://mempool.space/address/{addr}")

        nodes = [GraphNode("btc_address", addr)]
        edges: list[GraphEdge] = []

        # --- Common-input clustering: addresses co-spent WITH `addr` ---------
        cluster: set[str] = set()
        for tx in (txs or [])[:25]:
            in_addrs = [i.get("prevout", {}).get("scriptpubkey_address")
                        for i in tx.get("vin", []) if i.get("prevout")]
            if addr in in_addrs:                       # our address was an input
                for a in in_addrs:
                    if a and a != addr:
                        cluster.add(a)
        for a in sorted(cluster):
            nodes.append(GraphNode("btc_address", a, props={"cluster_with": addr}))
            edges.append(GraphEdge(f"btc_address:{addr}", f"btc_address:{a}",
                                   "same_owner", props={"heuristic": "common-input"}))

        # --- Chain-follow: destinations of the most recent spends (1 hop) ----
        flows: list[tuple[str, int]] = []
        for tx in (txs or [])[:10]:
            in_addrs = [i.get("prevout", {}).get("scriptpubkey_address")
                        for i in tx.get("vin", []) if i.get("prevout")]
            if addr not in in_addrs:
                continue                                # only spends FROM addr
            for o in tx.get("vout", []):
                dst = o.get("scriptpubkey_address")
                val = o.get("value", 0)
                if dst and dst != addr:
                    flows.append((dst, val))
        # Aggregate by destination.
        agg: dict[str, int] = {}
        for dst, val in flows:
            agg[dst] = agg.get(dst, 0) + val
        top = sorted(agg.items(), key=lambda x: -x[1])[:12]
        for dst, val in top:
            nodes.append(GraphNode("btc_address", dst))
            edges.append(GraphEdge(f"btc_address:{addr}", f"btc_address:{dst}",
                                   "funds_flow_to", props={"value_sat": val}))

        findings = [
            {"label": "Transactions analysed", "summary": str(min(len(txs or []), 25))},
            {"label": "Cluster (same-owner heuristic)",
             "summary": f"{len(cluster)} co-spent address(es) — likely same wallet",
             "values": sorted(cluster)[:20] or ["no multi-input spends seen"],
             "confidence": "medium" if cluster else "info"},
            {"label": "Funds flow to (1 hop)",
             "summary": f"{len(top)} destination(s)",
             "values": [f"{d} — {_btc(v)}" for d, v in top] or ["no outgoing spends"],
             "confidence": "info"},
            {"label": "Note",
             "summary": "Clustering is a heuristic, not proof; and this maps "
                        "addresses, never real identities.", "confidence": "info"},
        ]
        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if cluster or top else Confidence.INFO,
            source_url=f"https://mempool.space/address/{addr}",
            raw={"cluster": sorted(cluster), "flows": top}, nodes=nodes, edges=edges,
        )
