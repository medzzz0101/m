"""graph.py — the entity graph that ties a whole investigation together.

Modules emit nodes/edges; this class merges them from every module into ONE
deduplicated graph (nodes keyed by `type:value`). The graph is the protagonist
of the UI: it's what lets you SEE that a username, an email, and a domain are
all the same target's footprint.
"""
from __future__ import annotations

from dataclasses import asdict

from .base import GraphEdge, GraphNode


class EntityGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[tuple[str, str, str], GraphEdge] = {}

    def add_node(self, node: GraphNode) -> None:
        existing = self._nodes.get(node.id)
        if existing is None:
            self._nodes[node.id] = node
        else:
            # Merge metadata; keep the first non-empty label.
            existing.meta.update(node.meta)
            if not existing.label and node.label:
                existing.label = node.label

    def add_edge(self, edge: GraphEdge) -> None:
        key = (edge.source, edge.target, edge.kind)
        self._edges.setdefault(key, edge)

    def ingest(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
        for n in nodes:
            self.add_node(n)
        for e in edges:
            # Only keep edges whose endpoints exist (guards against typos).
            if e.source in self._nodes and e.target in self._nodes:
                self.add_edge(e)

    def to_dict(self) -> dict:
        # Degree count powers node sizing in the canvas renderer.
        degree: dict[str, int] = {nid: 0 for nid in self._nodes}
        for e in self._edges.values():
            degree[e.source] = degree.get(e.source, 0) + 1
            degree[e.target] = degree.get(e.target, 0) + 1
        nodes = []
        for nid, n in self._nodes.items():
            d = asdict(n)
            d["id"] = nid
            d["degree"] = degree.get(nid, 0)
            nodes.append(d)
        return {"nodes": nodes, "edges": [asdict(e) for e in self._edges.values()]}

    @property
    def size(self) -> tuple[int, int]:
        return (len(self._nodes), len(self._edges))
