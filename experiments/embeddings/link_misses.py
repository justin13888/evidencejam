"""Offline, 0 calls: how many wrong dev answers are the linker's fault? Decides ROADMAP item 24.

Runs the default pipeline on one gold file's dev split and puts every item in one bucket:
  correct
  ans:side_empty      gold answered, a side linked to nothing (embeddings could help)
  ans:no_gold_edge    gold answered, both sides linked, no gold edge among the candidates (wrong link)
  ans:downstream      gold answered, a gold edge was retrieved, answer still wrong
  empty:answered      gold no_evidence, we answered (linked too broadly or downstream)

    bash -c '. scripts/env.sh; "$PY" experiments/embeddings/link_misses.py experiments/devsets/class_gold.yaml'
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from camoreasoning.config import load_settings
from camoreasoning.contracts import Question
from camoreasoning.evaluate import is_correct, load_devsets
from camoreasoning.pipeline import Pipeline, make_context


def bucket(g, a, t) -> str:
    if is_correct(g, a):
        return "correct"
    if g.status != "answered":
        return "empty:answered"
    f, c = t.frame, t.candidates
    if f is None or f.cause.empty or f.outcome.empty:
        return "ans:side_empty"
    got = set(c.forward) | set(c.reversed) if c else set()
    return "ans:downstream" if got & set(g.edge_ids) else "ans:no_gold_edge"


def main(path: str) -> dict:
    gold = load_devsets([Path(path)], split="dev")
    ctx = make_context(load_settings(), out_dir=Path(".cache/energy"))
    answers, traces = Pipeline(ctx).run([Question(g.id, g.question) for g in gold])
    rows = [(g, bucket(g, a, t), t) for g, a, t in zip(gold, answers, traces, strict=True)]
    counts = Counter(b for _, b, _ in rows)
    empty = [
        {"id": g.id, "q": g.question, "cause": t.frame.cause.empty, "outcome": t.frame.outcome.empty}
        for g, b, t in rows
        if b == "ans:side_empty" and t.frame
    ]
    return {"file": path, "n": len(gold), "linker": ctx.settings.strategies.get("linker"),
            "counts": dict(counts.most_common()), "side_empty": empty}  # fmt: skip


if __name__ == "__main__":
    out = {}
    for p in sys.argv[1:]:
        r = main(p)
        out[Path(p).stem] = r
        print(Path(p).stem, r["n"], json.dumps(r["counts"]))
        for e in r["side_empty"][:12]:
            print("   ", e["id"], e["q"], "| empty:", "cause" * e["cause"], "outcome" * e["outcome"])
    Path("experiments/results/link_misses.json").write_text(json.dumps(out, indent=1))
