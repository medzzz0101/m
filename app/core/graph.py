"""
core/graph.py
=============
The correlation core. This is what turns a pile of independent lookups into an
"engine": every module contributes typed nodes and edges, and the graph
DEDUPES and LINKS them so relationships emerge across modules.

Example: the `dns_full` module says  domain --resolves_to--> ip.
         the `reverse_ip` module says ip --hosts--> otherDomain.
The graph stitches those into a path  domain -> ip -> otherDomain  that neither
module knew about alone. That cross-module linkage is the whole value.

A node's identity is `type:value` (see GraphNode.id), so two modules mentioning
the same IP automatically collapse onto one node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import GraphEdge, GraphNode

# Canonical node types (kept as a documented allow-list so the UI can colour
# them consistently). Modules SHOULD use these; unknown types still work but
# render with a default colour.
NODE_TYPES = [
    "org", "domain", "subdomain", "ip", "host", "tech", "cert", "asn",
    "btc_address", "eth_address", "tx", "image", "geo", "username",
    "email", "favicon", "service", "cloud_bucket",
]

# Canonical edge labels — the verbs of the graph.
EDGE_TYPES = [
    "resolves_to", "hosted_on", "runs_tech", "has_subdomain", "issued_cert",
    "same_owner", "funds_flow_to", "taken_on", "located_at", "shares_favicon",
    "redirects_to", "exposes", "related_to",
]


@dataclass
class EntityGraph:
    """An in-memory, per-target graph. Cheap to build, easy to serialise."""

    # id -> node dict.  We store dicts (not GraphNode) so merging props is easy.
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    # (src, dst, label) -> edge dict.  The triple key dedupes identical edges.
    edges: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)

    # ----------------------------------------------------------------------
    def add_node(self, node: GraphNode) -> str:
        """Insert or MERGE a node. Returns its id."""
        nid = node.id
        if nid in self.nodes:
            # Merge: keep existing, union props, prefer a non-empty label.
            existing = self.nodes[nid]
            existing["props"].update({k: v for k, v in node.props.items() if v is not None})
            if node.label and not existing.get("label"):
                existing["label"] = node.label
            existing["degree"] = existing.get("degree", 0)
        else:
            self.nodes[nid] = {
                "id": nid,
                "type": node.type,
                "value": node.value,
                "label": node.label or node.value,
                "props": dict(node.props),
                "degree": 0,
                "findings": [],   # filled in by attach_findings()
            }
        return nid

    def add_edge(self, edge: GraphEdge) -> None:
        """Insert or merge an edge (deduped by src+dst+label)."""
        key = (edge.src.lower(), edge.dst.lower(), edge.label)
        if key in self.edges:
            self.edges[key]["props"].update(edge.props)
            return
        self.edges[key] = {
            "src": edge.src.lower(),
            "dst": edge.dst.lower(),
            "label": edge.label,
            "props": dict(edge.props),
        }

    # ----------------------------------------------------------------------
    def ingest(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
        """Merge a module's contribution in one call."""
        for n in nodes:
            self.add_node(n)
        for e in edges:
            self.add_edge(e)

    def attach_finding(self, node_id: str, module: str, summary: str) -> None:
        """Record that `module` produced a finding about a node (for the
        click-a-node-to-see-findings UX). Safe if the node doesn't exist."""
        n = self.nodes.get(node_id.lower())
        if n is not None:
            n["findings"].append({"module": module, "summary": summary})

    # ----------------------------------------------------------------------
    def _compute_degrees(self) -> None:
        """Edge-count per node — used for node sizing in the graph view."""
        for n in self.nodes.values():
            n["degree"] = 0
        for e in self.edges.values():
            if e["src"] in self.nodes:
                self.nodes[e["src"]]["degree"] += 1
            if e["dst"] in self.nodes:
                self.nodes[e["dst"]]["degree"] += 1

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the {nodes:[...], edges:[...]} shape the frontend graph
        view (and the JSON export) consumes."""
        self._compute_degrees()
        return {
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
            "stats": {
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "by_type": self._counts_by_type(),
            },
        }

    def _counts_by_type(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for n in self.nodes.values():
            out[n["type"]] = out.get(n["type"], 0) + 1
        return out

    # ----------------------------------------------------------------------
    def neighbors(self, node_id: str) -> list[str]:
        """All node ids directly connected to `node_id` (used by pivoting)."""
        nid = node_id.lower()
        out = set()
        for e in self.edges.values():
            if e["src"] == nid:
                out.add(e["dst"])
            elif e["dst"] == nid:
                out.add(e["src"])
        return list(out)
