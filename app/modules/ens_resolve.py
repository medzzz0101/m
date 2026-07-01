"""
modules/ens_resolve.py
======================
Resolve between an ENS name (like vitalik.eth) and its Ethereum address — in both
directions — using a public resolver (ensideas, no key). ENS is public on-chain
naming; this maps a human-readable name to the address it points at (and back),
plus the avatar the name publishes.

On-chain / public-naming data only.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


class EnsResolveModule(BaseModule):
    key = "ens_resolve"
    name = "ENS resolver"
    category = Category.BLOCKCHAIN
    subtitle = "*.eth ↔ address"
    accepts = (InputType.DOMAIN, InputType.ETH_ADDRESS)
    needs_network = True
    description = (
        "Resolves an ENS name (e.g. vitalik.eth) to its Ethereum address and back, "
        "with the published avatar. Public on-chain naming data."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip().lower()
        # Only act on .eth names or eth addresses.
        if not (v.endswith(".eth") or (v.startswith("0x") and len(v) == 42)):
            return self.result(
                findings=[{"label": "ENS", "summary": "Not an ENS name (*.eth) or "
                           "ETH address — nothing to resolve."}],
                confidence=Confidence.INFO)
        url = f"https://api.ensideas.com/ens/resolve/{v}"
        try:
            data = await fetch_json(ctx, url, ttl=3600, namespace="ens")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"ENS resolve failed: {exc}", source_url=url)

        address = data.get("address")
        name = data.get("name")
        if not address and not name:
            return self.result(
                findings=[{"label": "ENS", "summary": f"No ENS record for {v}."}],
                confidence=Confidence.INFO, source_url=url)

        findings = [
            {"label": "Name", "summary": name or "—", "confidence": "high"},
            {"label": "Address", "summary": address or "—"},
        ]
        if data.get("avatar"):
            findings.append({"label": "Avatar", "values": [data["avatar"]]})

        nodes, edges = [], []
        if name and address:
            nodes = [GraphNode("eth_address", address.lower(), label=name),
                     GraphNode("domain", name)]
            edges = [GraphEdge(f"domain:{name}", f"eth_address:{address.lower()}",
                               "same_owner", props={"via": "ENS"})]
        return self.result(
            findings=findings, confidence=Confidence.HIGH,
            source_url=f"https://app.ens.domains/{name or v}",
            raw=data, nodes=nodes, edges=edges,
        )
