"""Build the 500-question timing set for ROADMAP item 22 ("500 questions finish in under 60 s").

    .venv/bin/python experiments/release/questions_500.py   # -> experiments/release/questions_500.yaml

Mix, in this order, deduplicated by text:
1. the free-form competency questions in questions.yaml (the slow path: they may need the batched LLM call);
2. every devset question (class wording, paraphrases, node wording, generated);
3. seeded template questions over taxonomy class pairs ("What effect does X have on Y?"), the hidden-set
   template, until there are 500.
Timing only. It has no gold, and is never scored.
"""

from __future__ import annotations

import random
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_suffix(".yaml")
N = 500
SEED = 22


def main() -> None:
    texts: list[str] = []
    for q in yaml.safe_load((ROOT / "questions.yaml").read_text(encoding="utf-8"))["questions"]:
        texts.append(" ".join(q["question"].split()))
    for p in sorted((ROOT / "experiments" / "devsets").glob("*.yaml")):
        for it in yaml.safe_load(p.read_text(encoding="utf-8")).get("items") or []:
            texts.append(" ".join(str(it["question"]).split()))
    rows = yaml.safe_load((ROOT / "taxonomy" / "classes.yaml").read_text(encoding="utf-8"))["classes"]
    causes = sorted(c["label"] for c in rows if c.get("kind") == "cause")
    outcomes = sorted(c["label"] for c in rows if c.get("kind") == "outcome")
    pairs = [(c, o) for c in causes for o in outcomes]
    random.Random(SEED).shuffle(pairs)
    texts += [f"What effect does {c.lower()} have on {o.lower()}?" for c, o in pairs]
    seen, qs = set(), []
    for t in texts:
        if t.lower() not in seen:
            seen.add(t.lower())
            qs.append({"id": f"t{len(qs) + 1:03d}", "question": t})
        if len(qs) == N:
            break
    OUT.write_text(
        "# Timing set for ROADMAP item 22. Built by questions_500.py; no gold, never scored.\n"
        + yaml.safe_dump({"questions": qs}, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )
    print(f"{len(qs)} questions -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
