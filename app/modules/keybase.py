"""
modules/keybase.py
==================
Look up a Keybase user's PUBLIC cryptographic identity proofs. Keybase lets people
PUBLISH verifiable links between their Keybase account and other accounts
(Twitter, GitHub, a website, a PGP key). This reads those self-published, publicly
verifiable proofs via Keybase's public API (no key).

These are proofs the person chose to publish and cryptographically sign — public
by design. We surface what they linked; we don't infer anything hidden.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


class KeybaseModule(BaseModule):
    key = "keybase"
    name = "Keybase proofs"
    category = Category.IDENTITY
    subtitle = "Self-published account proofs"
    accepts = (InputType.USERNAME,)
    needs_network = True
    description = (
        "Reads a Keybase user's PUBLIC, self-published cryptographic proofs "
        "(linked Twitter/GitHub/websites, PGP key). Public-by-design data."
    )

    async def run(self, value: str, ctx: RunContext):
        user = value.strip().lstrip("@")
        url = (f"https://keybase.io/_/api/1.0/user/lookup.json?usernames={user}"
               "&fields=proofs_summary,public_keys,basics")
        try:
            data = await fetch_json(ctx, url, ttl=3600, namespace="keybase")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Keybase lookup failed: {exc}", source_url=url)

        them = (data.get("them") or [None])
        them = them[0] if them else None
        if not them:
            return self.result(
                findings=[{"label": "Keybase", "summary": f"No Keybase user '{user}'."}],
                confidence=Confidence.INFO, source_url=f"https://keybase.io/{user}")

        proofs = (them.get("proofs_summary") or {}).get("all") or []
        pgp = them.get("public_keys", {}).get("primary", {}).get("key_fingerprint")

        findings = [{"label": "Keybase", "summary": f"keybase.io/{user}",
                     "confidence": "high"}]
        by_type = {}
        for pr in proofs:
            by_type.setdefault(pr.get("proof_type", "?"), []).append(
                f"{pr.get('nametag')} ({pr.get('service_url') or pr.get('proof_type')})")
        for ptype, items in by_type.items():
            findings.append({"label": f"Proof: {ptype}", "values": items})
        if pgp:
            findings.append({"label": "PGP fingerprint", "summary": pgp})

        # Graph: link the keybase handle to each proven account.
        nodes = [GraphNode("username", user, label=f"keybase/{user}")]
        edges: list[GraphEdge] = []
        for pr in proofs:
            tag = pr.get("nametag")
            if tag:
                nodes.append(GraphNode("service", f"{pr.get('proof_type')}:{tag}",
                                       label=f"{pr.get('proof_type')}/{tag}"))
                edges.append(GraphEdge(f"username:{user}",
                                       f"service:{pr.get('proof_type')}:{tag}",
                                       "same_owner", props={"via": "keybase-proof"}))

        return self.result(
            findings=findings, confidence=Confidence.MEDIUM,
            source_url=f"https://keybase.io/{user}",
            raw={"proofs": proofs, "pgp": pgp}, nodes=nodes, edges=edges,
        )
