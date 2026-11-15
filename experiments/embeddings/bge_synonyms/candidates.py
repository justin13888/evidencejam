"""Offline: BGE proposes classes for graph wording no class synonym matches; an audit decides (#24 follow-up).

The `embed` linker (GloVe) linked more wrong than right on the synonym probe, and bge-base-en-v1.5 was
better but still wrong too often to link at runtime (~40% wrong at a usable gap). Its top 3 held the
right class for 37 of 63 probe sides, which is good enough to *propose* synonyms. So BGE runs here,
offline, never at runtime:

1. Terms: the free-text `entity_term` of every node on an edge that no class phrase matches
   (`node_labeler/curated.lexical`), lower-cased and deduplicated. CURIEs carry no words and are skipped.
2. Each term and each class phrase (label, label parts split on & / , ( and synonyms without `*`) is
   embedded with bge-base-en-v1.5; a class scores its best cosine. Intervention-only terms see cause
   classes only, as in the node labeller.
3. Output: audit chunks audit/in_NNNN.jsonl for the auditor (AUDIT.md): term, node count, example node
   names, the committed LLM labels of those nodes, BGE top 3. The auditor sees
   the candidates; BGE only orders them.

Not a runtime dependency. Run in a separate venv:

    uv venv /tmp/bge && uv pip install -p /tmp/bge/bin/python sentence-transformers PyYAML
    PYTHONPATH=src /tmp/bge/bin/python experiments/embeddings/bge_synonyms/candidates.py
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from sentence_transformers import SentenceTransformer

from camoreasoning.graph import load_graph
from camoreasoning.strategies.node_labeler.curated import CURIE, lexical
from camoreasoning.taxonomy import load_taxonomy

HERE = Path(__file__).resolve().parent
MODEL = "BAAI/bge-base-en-v1.5"
TOP = 3
CHUNK = 150  # terms per audit chunk


def class_phrases(tax) -> list[tuple[str, str]]:
    out = []
    for c in tax.classes.values():
        parts = [p.strip() for p in re.split(r"[&/,()]", c.label) if p.strip()]
        for p in dict.fromkeys([c.label.lower(), *parts, *(s.replace("*", "").strip() for s in c.synonyms)]):
            if p:
                out.append((c.id, p))
    return out


def main() -> None:
    g, tax = load_graph(), load_taxonomy()
    on_edge = {e[k] for e in g.edges.values() for k in ("subject", "object")}
    nodes = {n: g.nodes[n] for n in sorted(on_edge) if n in g.nodes}
    hits = lexical(tax, nodes)
    llm = defaultdict(set)
    for lb in tax.labels:
        if lb.source == "llm":
            llm[lb.node_id].add(lb.class_id)
    terms: dict[str, dict] = {}
    for nid, n in nodes.items():
        et = " ".join(str(n.get("entity_term") or "").lower().split())
        if nid in hits or not et or CURIE.match(et):
            continue
        t = terms.setdefault(et, {"term": et, "nodes": 0, "examples": [], "types": set(), "llm_labels": set()})
        t["nodes"] += 1
        if len(t["examples"]) < 3:
            t["examples"].append(str(n.get("name") or ""))
        t["types"].add(n.get("entity_type") or "")
        t["llm_labels"] |= llm.get(nid, set())

    phrases = class_phrases(tax)
    cause_ids = {c.id for c in tax.of_kind("cause")}
    model = SentenceTransformer(MODEL, device="cpu")
    pv = model.encode([p for _, p in phrases], normalize_embeddings=True, batch_size=64)
    rows = sorted(terms.values(), key=lambda t: (-t["nodes"], t["term"]))
    tv = model.encode([t["term"] for t in rows], normalize_embeddings=True, batch_size=64)
    sims = tv @ pv.T
    for i, t in enumerate(rows):
        only_cause = t["types"] == {"management_intervention"}
        best: dict[str, float] = {}
        for j, (cid, _) in enumerate(phrases):
            if only_cause and cid not in cause_ids:
                continue
            best[cid] = max(best.get(cid, -1.0), float(sims[i, j]))
        top = sorted(best.items(), key=lambda x: -x[1])[:TOP]
        t["bge_top3"] = [[cid, round(s, 3)] for cid, s in top]
        t["types"], t["llm_labels"] = sorted(t["types"]), sorted(t["llm_labels"])

    audit = HERE / "audit"
    audit.mkdir(exist_ok=True)
    for k in range(0, len(rows), CHUNK):
        part = [{"id": f"T{k + i + 1:04d}", **{f: t[f] for f in ("term", "nodes", "examples", "types",
                 "llm_labels", "bge_top3")}} for i, t in enumerate(rows[k : k + CHUNK])]  # fmt: skip
        (audit / f"in_{k // CHUNK + 1:04d}.jsonl").write_text("".join(json.dumps(p) + "\n" for p in part))
    print(json.dumps({"nodes_on_edges": len(nodes), "lexical": len(hits), "terms": len(rows),
                      "chunks": -(-len(rows) // CHUNK)}))  # fmt: skip


if __name__ == "__main__":
    main()
