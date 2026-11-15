"""Issue #8: why no_evidence precision/recall miss 0.9 on class-level dev gold. 0 LLM calls.

    PYTHONPATH=src python experiments/gold/no_evidence_confusion.py [devset.yaml ...]   # default: class_gold.yaml

Runs the default pipeline on the dev split, then sorts every no_evidence error by the first stage that
explains it, mechanically:

- `linker:unlinked` - a side linked no class and no node, so nothing could be retrieved.
- `retrieval:gold_edges_missed` (false no_evidence) - both sides linked to something, but no gold edge
  reached the votes: its endpoints sit outside the retrieved node sets (`node_labels` put them in other
  classes, or the linker picked a class or nodes that miss them).
- `retrieval:edges_gold_rejects` (missed no_evidence) - both sides linked and votes were included, but
  gold (strict class membership, CLASS.md) holds no edge: `node_labels` put nodes in the linked classes
  that the labeller judged outside them, or the linker picked a neighbouring class.
- `other` - anything else (a gold edge reached the votes but none was included, ...).

Which of `node_labels` or the linker is at fault is not mechanical; read the rows. Writes
experiments/gold/no_evidence_confusion.json: counts, metrics and one row per error with the included
(or gold) edges' endpoint names and their `node_labels` classes, so each call can be checked.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from camoreasoning.config import CACHE_DIR, DEVSETS_DIR, load_settings
from camoreasoning.contracts import Question
from camoreasoning.evaluate import load_devsets
from camoreasoning.pipeline import Pipeline, make_context

OUT = Path(__file__).resolve().parent / "no_evidence_confusion.json"
SHOW = 5  # edges listed per error row


def endpoint(ctx, node_id: str) -> dict:
    return {"name": ctx.graph.nodes[node_id].get("name"),
            "classes": sorted(lb.class_id for lb in ctx.taxonomy.classes_of(node_id))}  # fmt: skip


def edge_row(ctx, edge_id: str) -> dict:
    e = ctx.graph.edges[edge_id]
    return {"edge": edge_id, "predicate": e.get("predicate"), "negated": bool(e.get("negated")),
            "subject": endpoint(ctx, e["subject"]), "object": endpoint(ctx, e["object"])}  # fmt: skip


def cause_of(g, t) -> str:
    f, c = t.frame, t.candidates
    if f is None or c is None:
        return "other"
    if f.cause.empty or f.outcome.empty:
        return "linker:unlinked"
    if g.status == "answered":
        edges = t.verdict and {v.edge_id for v in t.verdict.votes}
        reached = [e for e in g.edge_ids if e in (edges or ())]
        return "other" if reached else "retrieval:gold_edges_missed"
    return "retrieval:edges_gold_rejects"


def main(paths: list[Path]) -> dict:
    gold = load_devsets(paths, "dev")
    ctx = make_context(load_settings(), out_dir=CACHE_DIR / "no_evidence_confusion")
    answers, traces = Pipeline(ctx).run([Question(g.id, g.question) for g in gold])
    by_a, by_t = {a.id: a for a in answers}, {t.question.id: t for t in traces}
    confusion: Counter = Counter()
    rows = []
    for g in gold:
        a, t = by_a[g.id], by_t[g.id]
        gold_ne, pred_ne = g.status == "no_evidence", a.status == "no_evidence"
        confusion[("tp" if gold_ne else "fp") if pred_ne else ("fn" if gold_ne else "tn")] += 1
        if gold_ne == pred_ne:
            continue
        f = t.frame
        shown = list(g.edge_ids) if pred_ne else [v.edge_id for v in t.verdict.votes if v.included]
        rows.append({
            "id": g.id, "error": "missed_no_evidence" if gold_ne else "false_no_evidence", "question": g.question,
            "gold": [g.status, g.direction], "pred": [a.status, a.direction], "cause": cause_of(g, t),
            "linked": {"cause": [r.id for r in f.cause.classes], "outcome": [r.id for r in f.outcome.classes]}
            if f else None,
            "edges": [edge_row(ctx, e) for e in shown[:SHOW]], "n_edges": len(shown),
        })  # fmt: skip
    tp, fp, fn = confusion["tp"], confusion["fp"], confusion["fn"]
    return {
        "files": [p.name for p in paths],
        "n": len(gold),
        "confusion": dict(sorted(confusion.items())),
        "no_evidence_precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "no_evidence_recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "errors_by_cause": dict(sorted(Counter((r["error"], r["cause"]) for r in rows).items(), key=str)),
        "rows": rows,
    }


if __name__ == "__main__":
    args = [Path(p) for p in sys.argv[1:]] or [DEVSETS_DIR / "class_gold.yaml"]
    res = main(args)
    res["errors_by_cause"] = {f"{k[0]} {k[1]}": n for k, n in res["errors_by_cause"].items()}
    OUT.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
