"""Offline: where does linking lose dev questions? No LLM calls.

For every dev gold item, compare the linker's classes with the classes of the gold edges' subject and
object nodes (taxonomy/node_labels.jsonl). Reports, per side:
  covered  - the gold edges' nodes carry at least one class (taxonomy ceiling)
  hit      - the linker picked one of those classes
  empty    - the linker picked nothing
For no-evidence items it reports how often the linker links both sides (the retriever then decides).

    bash -c '. scripts/env.sh; "$PY" experiments/energy/link_ceiling.py [linker]'
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from camoreasoning import registry
from camoreasoning.config import load_settings
from camoreasoning.contracts import Question
from camoreasoning.evaluate import load_devsets
from camoreasoning.pipeline import Pipeline, make_context

OUT = Path("experiments/results")


def main(name: str = "lexical_v2", split: str = "dev") -> dict:
    ctx = make_context(load_settings(), out_dir=Path(".cache/energy"))
    gold = load_devsets(split=split)
    p = Pipeline(ctx)
    parsed = [p.parse(Question(g.id, g.question)) for g in gold]
    frames = registry.get("linker", name).link(parsed, ctx)
    g_, tax = ctx.graph, ctx.taxonomy
    c = Counter()
    misses = []
    for g, f in zip(gold, frames, strict=True):
        # linked nodes count as their classes, so class- and node-linking strategies compare alike
        cause = {r.id for r in f.cause.classes} | {lb.class_id for r in f.cause.nodes for lb in tax.classes_of(r.id)}
        outcome = {r.id for r in f.outcome.classes} | {
            lb.class_id for r in f.outcome.nodes for lb in tax.classes_of(r.id)
        }
        if g.status != "answered" or not g.edge_ids:
            c["empty_n"] += 1
            c["empty_both_linked"] += bool(cause and outcome)
            continue
        c["ans_n"] += 1
        gc = {lb.class_id for e in g.edge_ids if e in g_.edges for lb in tax.classes_of(g_.edges[e]["subject"])}
        go = {lb.class_id for e in g.edge_ids if e in g_.edges for lb in tax.classes_of(g_.edges[e]["object"])}
        for side, got, want in (("cause", cause, gc), ("outcome", outcome, go)):
            c[f"{side}_covered"] += bool(want)
            c[f"{side}_hit"] += bool(got & want)
            c[f"{side}_empty"] += not got
        both = bool(cause & gc) and bool(outcome & go)
        c["both_covered"] += bool(gc) and bool(go)
        c["both_hit"] += both
        if not both:
            misses.append(
                {
                    "id": g.id,
                    "q": g.question,
                    "got": [sorted(cause), sorted(outcome)],
                    "want": [sorted(gc), sorted(go)],
                }
            )
    res = {"linker": name, "split": split, "counts": dict(c), "misses": misses}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"link_ceiling_{name}.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = main(*sys.argv[1:])
    print(json.dumps(r["counts"], indent=1))
    for m in r["misses"][:25]:
        print(m["id"], m["q"], "| got", m["got"], "| want", m["want"])
