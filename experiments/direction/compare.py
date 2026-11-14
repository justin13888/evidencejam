"""Item 6: how `sentence`+`studies` change verdicts vs `baseline` over every cause x outcome class pair.

No gold needed: frames are built straight from taxonomy classes, so this isolates retrieval-level
coverage from the linker. Output: experiments/results/direction_compare.json. 0 LLM calls.

    python experiments/direction/compare.py
"""

from __future__ import annotations

import json
from collections import Counter

from camoreasoning import registry
from camoreasoning.config import CACHE_DIR, RESULTS_DIR, Settings
from camoreasoning.contracts import Frame, ParsedQuestion, Question, Ref, Side
from camoreasoning.pipeline import make_context


def main() -> None:
    ctx = make_context(Settings(), out_dir=CACHE_DIR / "direction_compare")
    tax = ctx.taxonomy
    retr = registry.get("retriever", "baseline")
    engines = {
        "baseline": (registry.get("interpreter", "baseline"), registry.get("aggregator", "baseline")),
        "sentence+studies": (registry.get("interpreter", "sentence"), registry.get("aggregator", "studies")),
    }
    causes = [c for c in tax.classes.values() if c.kind in ("cause", "both")]
    outcomes = [c for c in tax.classes.values() if c.kind in ("outcome", "both")]
    pairs, changes, dist = 0, [], {k: Counter() for k in engines}
    transitions: Counter = Counter()
    for c in causes:
        for o in outcomes:
            if c.id == o.id:
                continue
            q = Question(f"{c.id}->{o.id}", f"What effect does {c.label} have on {o.label}?")
            frame = Frame(ParsedQuestion(q, c.label, o.label, True), Side(c.label, (Ref(c.id),)),
                          Side(o.label, (Ref(o.id),)), "regex", 1.0)  # fmt: skip
            cands = retr.retrieve(frame, ctx)
            if not (cands.forward or cands.reversed):
                continue
            pairs += 1
            out = {}
            for name, (interp, agg) in engines.items():
                v = agg.aggregate(interp.interpret(cands, ctx), cands, ctx)
                out[name] = (v.status, v.direction)
                dist[name][v.direction or v.status] += 1
            if out["baseline"] != out["sentence+studies"]:
                transitions[f"{out['baseline'][1] or out['baseline'][0]} -> "
                            f"{out['sentence+studies'][1] or out['sentence+studies'][0]}"] += 1  # fmt: skip
                changes.append({"pair": q.id, "n_forward": len(cands.forward), **{k: list(v) for k, v in out.items()}})
    result = {"pairs_with_edges": pairs, "changed": len(changes), "transitions": dict(transitions.most_common()),
              "distribution": {k: dict(v.most_common()) for k, v in dist.items()}, "changes": changes}  # fmt: skip
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "direction_compare.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "changes"}, indent=2))


if __name__ == "__main__":
    main()
