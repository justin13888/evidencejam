"""Issue #9 audit: relabel class-level items where a recall auditor found edges the gold pool missed.

    PYTHONPATH=src python experiments/devsets/class_set.py build          # adds meta.recall from found_part*.jsonl
    PYTHONPATH=src python -m camoreasoning annotate export class_gold --chunk 10   # recall edges appended last
    PYTHONPATH=src python experiments/gold/class_recall.py blind   # -> class_recall/blind.jsonl (flagged items)
    # a fresh labeller writes class_recall/relabel.jsonl from class_gold/PROMPT.md + blind.jsonl only
    PYTHONPATH=src python experiments/gold/class_recall.py check
    PYTHONPATH=src python experiments/gold/class_recall.py fold    # -> class_recall/review_recall.csv
    python -m camoreasoning annotate review-import class_gold --file experiments/gold/class_recall/review_recall.csv

The relabel sees every candidate (pool, nominated, recall) without its source, and its label wins.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from camoreasoning import annotate as A

HERE = Path(__file__).resolve().parent / "class_recall"
TASK = "class_gold"


def items() -> dict[str, dict]:
    d = A.task_dir(TASK)
    return {it["id"]: it for c in A.chunks(TASK) for it in A._read_jsonl(d / "in" / f"{c}.jsonl")}


def flagged() -> list[str]:
    return sorted(r["id"] for p in sorted(HERE.glob("found_part*.jsonl")) for r in A._read_jsonl(p) if r.get("found"))


def blind() -> None:
    its = items()
    rows = [{"id": q, "question": its[q]["question"], "candidates": its[q]["candidates"]} for q in flagged()]
    A._write_jsonl(HERE / "blind.jsonl", rows)
    print(json.dumps({"flagged": [r["id"] for r in rows], "candidates": [len(r["candidates"]) for r in rows]}))


def check() -> None:
    its = items()
    errs, ok = A.check_rows(TASK, [its[q] for q in flagged()], A._read_jsonl(HERE / "relabel.jsonl"), A.vocab(TASK))
    print(json.dumps({"valid": len(ok), "errors": errs[:20]}))
    sys.exit(1 if errs else 0)


def fold() -> None:
    t, its = A.TASKS[TASK], items()
    model = {r["id"]: r for r in A.merged(TASK)}
    names, changed = list(t.fields), []
    with open(HERE / "review_recall.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "context", *[f"model_{k}" for k in names], "model_note", "ok", *[f"human_{k}" for k in names],
                    "reviewer", "comment"])  # fmt: skip
        for b in A._read_jsonl(HERE / "relabel.jsonl"):
            m = model[b["id"]]
            inv = {v: k for k, v in (m.get("_meta") or {}).get("refs", {}).items()}
            m_edges = sorted((inv.get(x["id"], x["id"]), x["effect"]) for x in m.get("edges") or [])
            b_edges = sorted((x["ref"], x["effect"]) for x in b.get("edges") or [])
            same = all(m.get(k) == b.get(k) for k in ("status", "direction", "certainty")) and m_edges == b_edges
            human = [""] * len(names)
            if not same:
                changed.append(b["id"])
                human = ["null" if b.get(k) is None else t.fields[k].fmt(b.get(k)) for k in names]
                human[names.index("edges")] = t.fields["edges"].fmt(b.get("edges")) or ";"
            shown = {**m, "edges": [{"ref": r, "effect": e} for r, e in m_edges]}
            model_cols = [t.fields[k].fmt(shown.get(k)) for k in names]
            ok = "y" if same else "n"
            w.writerow([b["id"], A._describe(its[b["id"]]), *model_cols, m.get("note", ""), ok, *human,
                        "llm:recall-relabel", b.get("note", "")])  # fmt: skip
    print(json.dumps({"changed": changed}))


if __name__ == "__main__":
    {"blind": blind, "check": check, "fold": fold}[sys.argv[1]]()
