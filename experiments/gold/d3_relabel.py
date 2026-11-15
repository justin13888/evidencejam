"""D3 relabel: gold items that a null edge with an `unchanged` cause can change (issue #9 audit).

The round-2 rubric dropped every edge whose cause is `unchanged`, including real nulls (`negated: true`).
The schema encodes a null as `negated: true` and never through `unchanged`, so PROMPT.md now lets those
nulls vote 0. This script relabels the items the old rule could have changed, blind, in a fresh session.

    PYTHONPATH=src python experiments/gold/d3_relabel.py select   # -> d3/blind.jsonl (ids, question, candidates)
    # a fresh labeller writes d3/relabel.jsonl from PROMPT.md + blind.jsonl only
    PYTHONPATH=src python experiments/gold/d3_relabel.py check    # schema check of relabel.jsonl
    PYTHONPATH=src python experiments/gold/d3_relabel.py fold     # -> d3/review_d3.csv (y/n/blank, see fold)
    python -m camoreasoning annotate review-import gold --file experiments/gold/d3/review_d3.csv

Selection is mechanical: any item whose candidates hold a null edge (negated or no_relationship) whose
subject is qualified `unchanged`, plus any item whose round-2 note mentions `unchanged`.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from camoreasoning import annotate as A

D3 = Path(__file__).resolve().parent / "d3"
UNCHANGED = re.compile(r"qualifier: unchanged")


def items() -> dict[str, dict]:
    d = A.task_dir("gold")
    return {it["id"]: it for c in A.chunks("gold") for it in A._read_jsonl(d / "in" / f"{c}.jsonl")}


def select() -> None:
    d, its = A.task_dir("gold"), items()
    notes = {r["id"] for c in A.chunks("gold") for r in A._read_jsonl(d / "out" / f"{c}.jsonl")
             if "unchanged" in (r.get("note") or "")}  # fmt: skip
    pick = []
    for qid, it in its.items():
        nulls = [
            c["ref"]
            for c in it["candidates"]
            if (c.get("negated") or c.get("language") == "no_relationship") and UNCHANGED.search(c["subject"])
        ]
        if nulls or qid in notes:
            pick.append(qid)
    D3.mkdir(exist_ok=True)
    A._write_jsonl(D3 / "blind.jsonl", ({"id": q, "question": its[q]["question"], "candidates": its[q]["candidates"]}
                                        for q in sorted(pick)))  # fmt: skip
    print(json.dumps({"selected": len(pick), "ids": sorted(pick)}))


def check() -> None:
    its = items()  # full in/ rows: check_rows reads the offered `refs`, which blind.jsonl leaves out
    blind = [its[r["id"]] for r in A._read_jsonl(D3 / "blind.jsonl")]
    errs, ok = A.check_rows("gold", blind, A._read_jsonl(D3 / "relabel.jsonl"), A.vocab("gold"))
    print(json.dumps({"valid": len(ok), "items": len(blind), "errors": errs[:20]}))
    sys.exit(1 if errs else 0)


def fold() -> None:
    t, its = A.TASKS["gold"], items()
    model = {r["id"]: r for r in A.merged("gold")}
    relabel = {r["id"]: r for r in A._read_jsonl(D3 / "relabel.jsonl")}
    names = list(t.fields)
    changed, skipped = [], []
    with open(D3 / "review_d3.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "context", *[f"model_{k}" for k in names], "model_note", "ok", *[f"human_{k}" for k in names],
                    "reviewer", "comment"])  # fmt: skip
        for qid in sorted(relabel):
            m, b = model[qid], relabel[qid]
            inv = {v: k for k, v in (m.get("_meta") or {}).get("refs", {}).items()}
            m_edges = sorted((inv.get(x["id"], x["id"]), x["effect"]) for x in m.get("edges") or [])
            b_edges = sorted((x["ref"], x["effect"]) for x in b.get("edges") or [])
            same = all(m.get(k) == b.get(k) for k in ("status", "direction", "certainty")) and m_edges == b_edges
            # Only D3-driven changes win: every edge that differs must be a null with an `unchanged` cause.
            # Other differences are labeller disagreement, not the rule change; they are left out (ok blank).
            nulls = {
                c["ref"]
                for c in its[qid]["candidates"]
                if (c.get("negated") or c.get("language") == "no_relationship") and UNCHANGED.search(c["subject"])
            }
            diff = {r for r, _ in set(m_edges) ^ set(b_edges)}
            d3 = not same and diff and diff <= nulls
            human = [""] * len(names)
            if not same and not d3:
                skipped.append(qid)
            if d3:
                changed.append(qid)
                human = ["null" if b.get(k) is None else t.fields[k].fmt(b.get(k)) for k in names]
                human[names.index("edges")] = t.fields["edges"].fmt(b.get("edges")) or ";"
            shown = {**m, "edges": [{"ref": r, "effect": e} for r, e in m_edges]}
            w.writerow([qid, A._describe(its[qid]), *[t.fields[k].fmt(shown.get(k)) for k in names], m.get("note", ""),
                        "y" if same else "n" if d3 else "", *human, "llm:d3-relabel",
                        b.get("note", "")])  # fmt: skip
    print(json.dumps({"relabelled": len(relabel), "changed_d3": changed, "skipped_non_d3": skipped}))


if __name__ == "__main__":
    {"select": select, "check": check, "fold": fold}[sys.argv[1]]()
