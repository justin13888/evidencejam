"""Offline: seeds for a reworded-question probe of `linker/embed` (ROADMAP 24).

Samples N graph edges (fixed seed) whose subject and object both carry a class label of the right kind,
spread over class pairs. Each seed shows only the two nodes' own wording. A model that has not seen
taxonomy/ rewrites each side in different words (synonyms, lay terms), so the answer key is the nodes'
classes and the wording is not ours. Writes experiments/embeddings/synonym_probe/in_K.jsonl (CHUNK per
file) and key.jsonl (never shown to the writer).

    bash -c '. scripts/env.sh; "$PY" experiments/embeddings/synonym_seeds.py'
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from camoreasoning.graph import load_graph
from camoreasoning.taxonomy import load_taxonomy

N, CHUNK, SEED = 80, 40, 24
OUT = Path("experiments/embeddings/synonym_probe")


def text(node: dict) -> str:
    return str(node.get("name") or node.get("entity_term") or "").strip()


def main() -> None:
    g, tax = load_graph(), load_taxonomy()
    kind = {c.id: c.kind for c in tax.classes.values()}

    def classes(nid: str, k: str) -> list[str]:
        return sorted({lb.class_id for lb in tax.classes_of(nid) if kind[lb.class_id] in (k, "both")})

    by_pair: dict[tuple, list[str]] = {}
    for eid, e in g.edges.items():
        cs, co = classes(e["subject"], "cause"), classes(e["object"], "outcome")
        if cs and co and text(g.nodes[e["subject"]]) and text(g.nodes[e["object"]]):
            by_pair.setdefault((cs[0], co[0]), []).append(eid)
    rng = random.Random(SEED)
    pairs = sorted(by_pair)
    rng.shuffle(pairs)
    picked = [rng.choice(by_pair[p]) for p in pairs[:N]]
    OUT.mkdir(parents=True, exist_ok=True)
    key = []
    for i, eid in enumerate(picked):
        e = g.edges[eid]
        sid = f"S{i + 1:03d}"
        seed = {"id": sid, "cause": text(g.nodes[e["subject"]]), "outcome": text(g.nodes[e["object"]])}
        with (OUT / f"in_{i // CHUNK + 1}.jsonl").open("a" if i % CHUNK else "w") as f:
            f.write(json.dumps(seed) + "\n")
        key.append({"id": sid, "edge": eid, **seed,
                    "cause_classes": classes(e["subject"], "cause"),
                    "outcome_classes": classes(e["object"], "outcome")})  # fmt: skip
    (OUT / "key.jsonl").write_text("".join(json.dumps(k) + "\n" for k in key))
    print(f"{len(picked)} seeds from {len(pairs)} class pairs -> {OUT}")


if __name__ == "__main__":
    main()
