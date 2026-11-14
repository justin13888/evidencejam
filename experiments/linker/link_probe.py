"""ROADMAP item 5: how often a linker maps template questions to the right class pair. 0 LLM calls.

Builds questions from the taxonomy (gold = the class pair) in three wordings and scores each side:
  exact   the only top class is the gold one
  tied    gold is among several top classes that tie
  wrong   top class(es) exist but gold is not among them
  none    nothing matched

    bash -c '. scripts/env.sh; "$PY" experiments/linker/link_probe.py [linker_name]'
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter

from camoreasoning.config import RESULTS_DIR
from camoreasoning.contracts import Question
from camoreasoning.pipeline import make_context
from camoreasoning.registry import discover, get

SEED = 11
PER_SET = 400


def questions(tax) -> dict[str, list[tuple[str, str, str]]]:
    rng = random.Random(SEED)
    causes, outcomes = tax.of_kind("cause"), tax.of_kind("outcome")
    pairs = [(rng.choice(causes), rng.choice(outcomes)) for _ in range(PER_SET)]

    def syn(c):
        return rng.choice(c.synonyms).replace("*", "") if c.synonyms else c.label

    return {
        "label": [(f"What effect does {c.label} have on {o.label}?", c.id, o.id) for c, o in pairs],
        "synonym": [(f"What effect does {syn(c)} have on {syn(o)}?", c.id, o.id) for c, o in pairs],
        "paraphrase": [(f"How does {c.label} affect {o.label}?", c.id, o.id) for c, o in pairs],
    }


def grade(side, gold: str) -> str:
    ids = [r.id for r in side.classes]
    if not ids:
        return "none"
    if gold not in ids:
        return "wrong"
    return "exact" if len(ids) == 1 else "tied"


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    discover()
    ctx = make_context()
    parser, linker = get("parser"), get("linker", name)
    report, misses = {}, []
    for set_name, qs in questions(ctx.taxonomy).items():
        parsed = [parser.parse(Question(f"{set_name}{i}", t), ctx) for i, (t, _, _) in enumerate(qs)]
        frames = linker.link(parsed, ctx)
        counts = {"cause": Counter(), "outcome": Counter()}
        both = 0
        for (text, gc, go), f in zip(qs, frames, strict=True):
            c, o = grade(f.cause, gc), grade(f.outcome, go)
            counts["cause"][c] += 1
            counts["outcome"][o] += 1
            both += c == o == "exact"
            if not c == o == "exact":
                got = [[r.id for r in f.cause.classes], [r.id for r in f.outcome.classes]]
                misses.append({"set": set_name, "q": text, "gold": [gc, go], "got": got})
        n = len(qs)
        report[set_name] = {
            "n": n,
            "both_exact": round(both / n, 3),
            **{side: {k: round(v / n, 3) for k, v in cnt.items()} for side, cnt in counts.items()},
        }
    print(json.dumps(report, indent=1))
    out = RESULTS_DIR / f"link_probe_{name}.json"
    out.write_text(json.dumps({"linker": name, "report": report, "misses": misses[:200]}, indent=1))
    print(f"wrote {out} ({len(misses)} misses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
