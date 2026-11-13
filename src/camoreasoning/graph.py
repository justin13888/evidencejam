"""Read-only index over causal_graph.json. Records stay raw CAMO dicts: never invent fields."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from camoreasoning.config import GRAPH_PATH


@dataclass(frozen=True)
class Graph:
    nodes: dict[str, dict]
    edges: dict[str, dict]
    docs: dict[str, dict]
    out_edges: dict[str, tuple[str, ...]] = field(repr=False)
    in_edges: dict[str, tuple[str, ...]] = field(repr=False)
    meta: dict = field(default_factory=dict, repr=False)

    def subject(self, edge_id: str) -> dict:
        return self.nodes[self.edges[edge_id]["subject"]]

    def object(self, edge_id: str) -> dict:
        return self.nodes[self.edges[edge_id]["object"]]

    def doc(self, edge_id: str) -> dict:
        return self.docs.get(self.edges[edge_id].get("source_document", ""), {})

    def edges_between(self, subjects: set[str], objects: set[str]) -> list[str]:
        """Edge ids whose subject is in `subjects` and object in `objects` (graph order)."""
        if len(subjects) <= len(objects):
            ids = (e for n in subjects for e in self.out_edges.get(n, ()))
            hits = {e for e in ids if self.edges[e]["object"] in objects}
        else:
            ids = (e for n in objects for e in self.in_edges.get(n, ()))
            hits = {e for e in ids if self.edges[e]["subject"] in subjects}
        return sorted(hits, key=self.meta["order"].__getitem__)


def build_graph(raw: dict) -> Graph:
    nodes = {n["id"]: n for n in raw["nodes"]}
    edges = {e["id"]: e for e in raw["edges"]}
    out_e: dict[str, list[str]] = defaultdict(list)
    in_e: dict[str, list[str]] = defaultdict(list)
    for eid, e in edges.items():
        out_e[e["subject"]].append(eid)
        in_e[e["object"]].append(eid)
    meta = {k: v for k, v in raw.items() if k not in ("nodes", "edges", "source_documents")}
    meta["order"] = {eid: i for i, eid in enumerate(edges)}
    return Graph(
        nodes=nodes,
        edges=edges,
        docs={d["document_id"]: d for d in raw.get("source_documents", [])},
        out_edges={k: tuple(v) for k, v in out_e.items()},
        in_edges={k: tuple(v) for k, v in in_e.items()},
        meta=meta,
    )


@lru_cache(maxsize=2)
def load_graph(path: Path = GRAPH_PATH) -> Graph:
    with open(path, encoding="utf-8") as f:
        return build_graph(json.load(f))
