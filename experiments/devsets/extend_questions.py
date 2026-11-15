"""Issue #9 audit: append 60 forward edge seeds as experiments/annotate/questions/in/0006.jsonl (Q0181-Q0240).

    PYTHONPATH=src python experiments/devsets/extend_questions.py

Why: the first 180 seeds left 44% of gold empty (55 of 60 random pairs) against a ~1/3 target, and no item
covered `negative_predicates_double_negation`. These seeds are forward edges (answer-likely), never used
before, on concept pairs no earlier seed used, stratified by trap key. Chunks 0001-0005 are not touched.
Selection uses graph fields only (no taxonomy, D5) and a fixed seed, so it is reproducible.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict

from camoreasoning import annotate as A
from camoreasoning.graph import load_graph
from camoreasoning.signs import is_null_finding
from camoreasoning.strategies.devset_builder._traps import EdgeTraps, concept

SEED, START, CHUNK = 9, 181, "0006"
QUOTA = {  # trap key -> seeds; the rest are random signed edges
    "trap:negative_predicates_double_negation": 8,
    "trap:comparator_reference": 4,
    "trap:time_as_cause": 4,
    "trap:null": 6,
    "trap:removed_subject": 6,
    "trap:associational": 6,
    "trap:twin": 4,
}
TOTAL = 60


def main() -> None:
    g, rng = load_graph(), random.Random(SEED)
    d = A.task_dir("questions")
    old = [m for c in A.chunks("questions") if c != CHUNK for m in A._read_jsonl(d / "in" / f"{c}.meta.jsonl")]
    used_edges = {m["seed_edge"] for m in old if "seed_edge" in m}
    pair_key = lambda e: (concept(g.nodes[g.edges[e]["subject"]]), concept(g.nodes[g.edges[e]["object"]]))  # noqa: E731
    used_pairs = {pair_key(e) for e in used_edges}
    by_sentence = defaultdict(list)
    for eid, e in g.edges.items():
        by_sentence[(e.get("source_document"), e.get("original_sentence"))].append(eid)
    twins = {x for ids in by_sentence.values() if len(ids) > 1 for x in ids}
    traps = EdgeTraps(g)
    tags = {eid: A.edge_trap_tags(g, eid, twins) + traps.tags(eid) for eid in g.edges}
    # answer-likely: a directional predicate, and either a null or a sign-bearing edge
    ok = sorted(e for e in g.edges if e not in used_edges and pair_key(e) not in used_pairs
                and g.edges[e].get("predicate") not in ("moderates", "mediates", "precedes", "regulates")
                and (is_null_finding(g.edges[e]) or g.edges[e].get("predicate")))  # fmt: skip
    picked: list[str] = []
    taken_pairs: set = set()

    def take(pool: list[str], k: int) -> None:
        for e in rng.sample(pool, len(pool)):
            if k <= 0:
                return
            if e not in picked and pair_key(e) not in taken_pairs:
                picked.append(e)
                taken_pairs.add(pair_key(e))
                k -= 1

    for key, k in QUOTA.items():
        take([e for e in ok if key in tags[e]], k)
    take(ok, TOTAL - len(picked))
    items, metas = [], []
    for i, eid in enumerate(picked):
        qid = f"Q{START + i:04d}"
        view = A._edge_view(g, eid)
        items.append({"id": qid, "kind": "edge", "ask": "forward",
                      **{k: view[k] for k in ("subject", "predicate", "object", "sentence")}})  # fmt: skip
        metas.append({"id": qid, "seed_edge": eid, "hint_tags": A.edge_trap_tags(g, eid, twins)})
    A._write_jsonl(d / "in" / f"{CHUNK}.jsonl", items)
    A._write_jsonl(d / "in" / f"{CHUNK}.meta.jsonl", metas)
    count = defaultdict(int)
    for e in picked:
        for t in tags[e]:
            count[t] += 1
    print(json.dumps({"written": len(items), "first": items[0]["id"], "last": items[-1]["id"],
                      "by_tag": dict(sorted(count.items()))}))  # fmt: skip


if __name__ == "__main__":
    main()
