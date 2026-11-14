"""Check taxonomy/node_labels.jsonl against ROADMAP item 4's Done-when criteria.

    PYTHONPATH=src python experiments/verify_node_labels.py [--sample N] [--seed S]

Prints coverage, a polarity check on removed/absent/decreased nodes, and a seeded random sample of
labels (stratified by source) for a hand audit recorded in experiments/labels/node_label_audit.md.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import random

from camoreasoning.config import TAXONOMY_DIR
from camoreasoning.graph import load_graph
from camoreasoning.strategies.node_labeler.curated import INVERTED
from camoreasoning.taxonomy import load_taxonomy

NEGATIVE_QUALIFIERS = {"removed", "absent", "decreased", "terminated"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=100)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    g, t = load_graph(), load_taxonomy()

    labelled = {lb.node_id for lb in t.labels}
    both = sum(e["subject"] in labelled and e["object"] in labelled for e in g.edges.values())
    sources = collections.Counter(lb.source for lb in t.labels)
    digest = hashlib.sha256((TAXONOMY_DIR / "node_labels.jsonl").read_bytes()).hexdigest()[:12]
    print(f"classes {len(t.classes)}  labels {len(t.labels)}  sources {dict(sources)}  sha {digest}")
    print(f"nodes labelled {len(labelled)}/{len(g.nodes)} = {len(labelled) / len(g.nodes):.1%}")
    print(f"edges with both endpoints labelled {both}/{len(g.edges)} = {both / len(g.edges):.1%}  (target 80%)")
    unused = sorted(set(t.classes) - {lb.class_id for lb in t.labels})
    print(f"classes with no nodes: {unused}")

    bad = []
    neg = [lb for lb in t.labels if g.nodes[lb.node_id].get("state_or_change_qualifier") in NEGATIVE_QUALIFIERS]
    for lb in neg:
        name = str(g.nodes[lb.node_id].get("name") or "").lower()
        inverted = lb.class_id in INVERTED and INVERTED[lb.class_id].search(name)
        if lb.polarity != (1 if inverted else -1):
            bad.append(lb)
    print(f"polarity on removed/absent/decreased/terminated: {len(neg) - len(bad)}/{len(neg)} correct")
    for lb in bad[:10]:
        print(f"   wrong: {g.nodes[lb.node_id]['name'][:70]} -> {lb.class_id} {lb.polarity:+d}")

    rng = random.Random(args.seed)
    by_src = collections.defaultdict(list)
    for lb in t.labels:
        by_src[lb.source].append(lb)
    sample = []
    for _src, lbs in sorted(by_src.items()):
        k = round(args.sample * len(lbs) / len(t.labels))
        sample += rng.sample(lbs, min(k, len(lbs)))
    print(f"\naudit sample ({len(sample)} labels, seed {args.seed}):")
    for i, lb in enumerate(sample, 1):
        n = g.nodes[lb.node_id]
        print(f"{i:3}. [{lb.source:7}] {n['name'][:70]!s:70} | {n.get('state_or_change_qualifier')} "
              f"-> {lb.class_id} {lb.polarity:+d}")  # fmt: skip


if __name__ == "__main__":
    main()
