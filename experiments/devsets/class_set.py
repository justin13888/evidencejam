"""Issue #9 audit: build, gold and measure the class-level dev set.

    PYTHONPATH=src python experiments/devsets/class_set.py build    # -> experiments/devsets/class_generated.yaml
    PYTHONPATH=src python experiments/devsets/class_set.py gold     # -> experiments/devsets/class_gold.yaml
    PYTHONPATH=src python experiments/devsets/class_set.py measure  # recall of the taxonomy-free pool, rubric check

`gold` adds trap tags from the gold edges (inventory keys, graph fields only).

`measure` reports two things:
  - Pool-only gold: the labeller's own edge judgements restricted to edges the taxonomy-free lexical pool
    offered, with D2/D4 recomputed mechanically. It shows what gold would be without nominated edges.
  - Rubric arithmetic: the same mechanical D2/D4 recompute on all labelled edges, compared with the
    labeller's own direction and certainty, for both gold files. Disagreement there is labeller arithmetic
    error, not a judgement call.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from camoreasoning import annotate as A
from camoreasoning import registry
from camoreasoning.cli import load_generated
from camoreasoning.config import DEVSETS_DIR
from camoreasoning.evaluate import load_devsets, save_devset
from camoreasoning.pipeline import make_context
from camoreasoning.strategies.devset_builder._traps import RENAME, EdgeTraps

GEN, GOLD = DEVSETS_DIR / "class_generated.yaml", DEVSETS_DIR / "class_gold.yaml"
GRADES = ("very_low", "low", "moderate")
ASSOC = ("associated_with", "correlated_with")


RECALL = Path(__file__).resolve().parents[1] / "gold" / "class_recall"


def recall_found() -> dict[str, list[str]]:
    """Edges the recall auditors found for no_evidence items (experiments/gold/class_recall/found_part*.jsonl)."""
    out: dict[str, list[str]] = {}
    for p in sorted(RECALL.glob("found_part*.jsonl")):
        for r in A._read_jsonl(p):
            if r.get("found"):
                out[r["id"]] = [x["edge_id"] for x in r["found"]]
    return out


def build() -> None:
    ctx = make_context()
    items = registry.get("devset_builder", "classlevel").build(ctx.taxonomy, ctx)
    found = recall_found()
    items = [replace(it, meta={**it.meta, "recall": found[it.id]}) if it.id in found else it for it in items]
    save_devset(GEN, items)
    print(json.dumps({"questions": len(items), "path": str(GEN)}))


def gold() -> None:
    ctx = make_context()
    g = ctx.graph
    items = load_generated(GEN)
    labelled = registry.get("gold_labeler", "class_annotated").label(items, ctx)
    by_sentence = defaultdict(list)
    for eid, e in g.edges.items():
        by_sentence[(e.get("source_document"), e.get("original_sentence"))].append(eid)
    twins = {x for ids in by_sentence.values() if len(ids) > 1 for x in ids}
    traps, out = EdgeTraps(g), []
    for it in labelled:
        extra = [t for e in it.edge_ids for t in (*(RENAME.get(x, x) for x in A.edge_trap_tags(g, e, twins)),
                                                 *traps.tags(e)) if t]  # fmt: skip
        out.append(type(it)(**{**it.__dict__, "tags": tuple(dict.fromkeys((*it.tags, *extra)))}))
    save_devset(GOLD, out)
    print(json.dumps({"labelled": len(out), "of": len(items), "path": str(GOLD)}))


def rubric(edges: list[tuple[str, int | None]], g) -> tuple[str, str | None, str | None]:
    """D2/D4 as written in experiments/annotate/gold/PROMPT.md, from (edge id, effect) pairs."""
    if not edges:
        return "no_evidence", None, None
    by_study = defaultdict(list)
    for e, x in edges:
        if x is not None:
            by_study[g.edges[e].get("source_document")].append(x)
    if not by_study:
        direction = "unclear"
    else:
        votes = []
        for xs in by_study.values():
            top = Counter(xs).most_common()
            votes.append("mixed" if len(top) > 1 and top[0][1] == top[1][1] else top[0][0])
        signed = [v for v in votes if v != "mixed"]
        win = Counter(signed).most_common(1)
        name = {1: "increase", -1: "decrease", 0: "no_effect"}
        direction = name[win[0][0]] if win and win[0][1] * 3 >= 2 * len(votes) else "mixed"
    grades = sorted(GRADES.index(g.edges[e].get("certainty_grade")) for e, _ in edges)
    level = grades[(len(grades) - 1) // 2]
    if direction == "mixed" or all(g.edges[e].get("predicate") in ASSOC for e, _ in edges):
        level = max(0, level - 1)
    return "answered", direction, GRADES[level]


def measure() -> None:
    g = make_context().graph
    rows = {r["id"]: r for r in A.merged("class_gold")}
    final = {x.id: x for x in load_devsets([GOLD])}
    flips = Counter()
    nominated_only = 0
    for qid, it in final.items():
        meta = rows[qid]["_meta"]
        ref_of = {eid: ref for ref, eid in meta["refs"].items()}
        pool = [(e, x) for e, x in it.edge_effects if meta["source"].get(ref_of.get(e)) == "pool"]
        nominated_only += len(pool) < len(it.edge_effects)
        full = (it.status, it.direction, it.certainty)
        alone = rubric(pool, g) if pool or it.status == "answered" else full
        flips["status" if alone[0] != full[0] else "direction" if alone[1] != full[1] else
              "certainty" if alone[2] != full[2] else "same"] += 1  # fmt: skip
    report = {"class_items": len(final), "items_using_nominated_edges": nominated_only,
              "pool_only_vs_final": dict(flips)}  # fmt: skip
    for name, path in (("node", DEVSETS_DIR / "gold_annotated.yaml"), ("class", GOLD)):
        agree, bad = 0, []
        items = load_devsets([path])
        for it in items:
            mech = rubric(list(it.edge_effects), g)
            if mech == (it.status, it.direction, it.certainty):
                agree += 1
            else:
                bad.append({"id": it.id, "label": [it.status, it.direction, it.certainty], "rubric": list(mech)})
        report[f"rubric_arithmetic_{name}"] = {"agree": agree, "n": len(items), "disagree": bad}
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    {"build": build, "gold": gold, "measure": measure}[sys.argv[1]]()
