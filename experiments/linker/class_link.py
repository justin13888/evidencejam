"""Issue #88: class-link accuracy of a linker on the class dev split. 0 LLM calls.

A dev item counts when its gold cause class and gold outcome class (experiments/devsets/class_seeds.jsonl)
are both among the classes the linker puts on that side. Also reports top-1 (gold is the sole class).

    bash -c '. scripts/env.sh; "$PY" experiments/linker/class_link.py [linker_name]'
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from camoreasoning.contracts import Question
from camoreasoning.evaluate import load_devsets
from camoreasoning.pipeline import make_context
from camoreasoning.registry import discover, get

GOLD = Path("experiments/devsets/class_gold.yaml")
SEEDS = Path("experiments/devsets/class_seeds.jsonl")


def main() -> int:
    discover()
    ctx = make_context()
    name = sys.argv[1] if len(sys.argv) > 1 else ctx.settings.strategies.get("linker")
    rows = (json.loads(x) for x in SEEDS.read_text(encoding="utf-8").splitlines() if x.strip())
    seeds = {f"C-{d['id']}": d for d in rows}
    gold = [g for g in load_devsets([GOLD], split="dev") if g.id in seeds]
    parser, linker = get("parser"), get("linker", name)
    frames = linker.link([parser.parse(Question(g.id, g.question), ctx) for g in gold], ctx)
    hit = top1 = 0
    misses = []
    for g, f in zip(gold, frames, strict=True):
        s = seeds[g.id]
        c, o = [r.id for r in f.cause.classes], [r.id for r in f.outcome.classes]
        ok = s["cause_class"] in c and s["outcome_class"] in o
        hit += ok
        top1 += c == [s["cause_class"]] and o == [s["outcome_class"]]
        if not ok:
            misses.append(f"  miss {g.id} | {g.question} | cause {s['cause_class']} -> {c}"
                          f" | outcome {s['outcome_class']} -> {o}")  # fmt: skip
    n = len(gold)
    print(f"linker={name or 'default'} n={n} linked={hit}/{n} ({hit / n:.3f}) top1={top1}/{n}")
    print("\n".join(misses))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
