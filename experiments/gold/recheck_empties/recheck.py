"""Issue #49: re-check the 4 node-level empties whose labeller wrote "candidates incomplete" (AUDIT.md finding 5).

Gold candidates come from a lexical top-60 prefilter, so D-Q0101, Q0121, Q0122 and Q0162 may be false empties.
A searcher read only questions.jsonl and causal_graph.json and wrote found.jsonl (as in class_recall/). A fresh
labeller then labels each item from PROMPT.md and blind.jsonl only: the item's own candidates plus the found
edges appended last, so earlier refs keep their meaning. An item flips only if the relabel cites edges that give
a direction (some edge with effect 1, -1 or 0); otherwise it stays no_evidence.

    PYTHONPATH=src python experiments/gold/recheck_empties/recheck.py blind    # -> blind.jsonl
    # a fresh labeller writes relabel.jsonl from experiments/annotate/gold/PROMPT.md + blind.jsonl only
    PYTHONPATH=src python experiments/gold/recheck_empties/recheck.py check    # schema check of relabel.jsonl
    PYTHONPATH=src python experiments/gold/recheck_empties/recheck.py extend   # flipped items: found refs -> in/
    PYTHONPATH=src python experiments/gold/recheck_empties/recheck.py fold     # -> review.csv
    python -m camoreasoning annotate review-import gold --file experiments/gold/recheck_empties/review.csv

`extend` appends a flipped item's found edges to its gold input row and meta refs, so `merge` accepts them. It is
idempotent, and it leaves every other row byte-identical.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from camoreasoning import annotate as A
from camoreasoning.graph import load_graph

HERE = Path(__file__).resolve().parent
TASK = "gold"


def _chunk_of() -> dict[str, str]:
    d = A.task_dir(TASK)
    return {it["id"]: c for c in A.chunks(TASK) for it in A._read_jsonl(d / "in" / f"{c}.jsonl")}


def _found() -> dict[str, list[str]]:
    return {r["id"]: r.get("found") or [] for r in A._read_jsonl(HERE / "found.jsonl")}


def extended() -> dict[str, tuple[dict, dict]]:
    """id -> (input row with found edges appended as new refs, meta refs). Already-offered edges keep their ref."""
    d, g, where = A.task_dir(TASK), load_graph(), _chunk_of()
    out = {}
    for qid, found in _found().items():
        it = next(x for x in A._read_jsonl(d / "in" / f"{where[qid]}.jsonl") if x["id"] == qid)
        meta = next(x for x in A._read_jsonl(d / "in" / f"{where[qid]}.meta.jsonl") if x["id"] == qid)
        refs = dict(meta["refs"])
        have = set(refs.values())
        cands = list(it["candidates"])
        for eid in found:
            if eid not in g.edges:
                raise SystemExit(f"{qid}: {eid} is not a graph edge")
            if eid in have:
                continue
            ref = f"e{len(refs) + 1}"
            refs[ref] = eid
            have.add(eid)
            cands.append(A._edge_view(g, eid, ref))
        out[qid] = ({**it, "candidates": cands, "refs": list(refs)}, refs)
    return out


def blind() -> None:
    ext = extended()
    A._write_jsonl(HERE / "blind.jsonl", ({"id": q, "question": it["question"], "candidates": it["candidates"]}
                                          for q, (it, _) in ext.items()))  # fmt: skip
    print(json.dumps({q: len(it["candidates"]) for q, (it, _) in ext.items()}))


def _relabel() -> dict[str, dict]:
    ext = extended()
    errs, ok = A.check_rows(TASK, [it for it, _ in ext.values()], A._read_jsonl(HERE / "relabel.jsonl"), A.vocab(TASK))
    if errs:
        raise SystemExit(json.dumps({"errors": errs[:20]}))
    return ok


def flips() -> dict[str, dict]:
    """Relabels that cite at least one edge with a direction (effect 1, -1 or 0)."""
    return {q: r for q, r in _relabel().items()
            if r["status"] == "answered" and any(x["effect"] is not None for x in r["edges"])}  # fmt: skip


def check() -> None:
    ok = _relabel()
    print(json.dumps({"valid": len(ok), "flips": sorted(flips())}))


def extend() -> None:
    d, ext, where, done = A.task_dir(TASK), extended(), _chunk_of(), []
    for qid in flips():
        it, refs = ext[qid]
        for name, new in ((f"{where[qid]}.jsonl", it), (f"{where[qid]}.meta.jsonl", None)):
            rows = A._read_jsonl(d / "in" / name)
            for i, r in enumerate(rows):
                if r["id"] == qid:
                    rows[i] = new if new is not None else {**r, "refs": refs}
            A._write_jsonl(d / "in" / name, rows)
        done.append(qid)
    print(json.dumps({"extended": done}))


def fold() -> None:
    t, ext, flip = A.TASKS[TASK], extended(), flips()
    model = {r["id"]: r for r in A.merged(TASK)}
    names = list(t.fields)
    with open(HERE / "review.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "context", *[f"model_{k}" for k in names], "model_note", "ok", *[f"human_{k}" for k in names],
                    "reviewer", "comment"])  # fmt: skip
        for b in A._read_jsonl(HERE / "relabel.jsonl"):
            qid, m = b["id"], model[b["id"]]
            human = [""] * len(names)
            if qid in flip:
                human = ["null" if b.get(k) is None else t.fields[k].fmt(b.get(k)) for k in names]
                refs = ext[qid][1]
                cited = ", ".join(f"{x['ref']}={refs[x['ref']]}:{x['effect']}" for x in b["edges"])
                note = f"{b.get('note') or ''} [cites {cited}]".strip()
            else:
                note = b.get("note") or ""
            # y: the relabel also finds no evidence. Blank: answered with no directional edge, kept by the flip rule.
            ok = "n" if qid in flip else "y" if b["status"] == "no_evidence" else ""
            w.writerow([qid, A._describe(ext[qid][0]), *[t.fields[k].fmt(m.get(k)) for k in names], m.get("note", ""),
                        ok, *human, "llm:recheck-relabel", note])  # fmt: skip
    print(json.dumps({"flipped": sorted(flip)}))


if __name__ == "__main__":
    {"blind": blind, "check": check, "extend": extend, "fold": fold}[sys.argv[1]]()
