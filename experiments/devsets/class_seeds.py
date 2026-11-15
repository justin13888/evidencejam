"""Issue #9 audit: class-pair seeds for the class-level dev set -> experiments/devsets/class_seeds.jsonl.

    PYTHONPATH=src python experiments/devsets/class_seeds.py

The hidden set asks about broad classes ("mulch & surface cover" -> "invasive / non-native species
abundance"). Seeds are (cause class, outcome class) pairs from taxonomy/classes.yaml, chosen by the gap
map's study counts only to stratify. Gold never sees the taxonomy: `class_gold` labels from edge sentences.

Mix (fixed seed): 58 pairs with evidence, spread over study-count bands; 30 empty pairs; 6 near-miss pairs
(a cause with evidence for an outcome, asked about that outcome's sibling); 6 time-since-disturbance pairs.
About half keep the exact class labels and half are paraphrased (sha1 of the id, odd = paraphrase).
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from camoreasoning.pipeline import make_context
from camoreasoning.strategies.extras.gapmap import band, study_counts

OUT = Path(__file__).resolve().parent / "class_seeds.jsonl"
SEED = 9
PER_BAND = {1: 15, 2: 13, 3: 15, 4: 15}
N_EMPTY, N_NEAR, N_TIME = 30, 6, 6
SIBLINGS = [
    ("native_abundance", "invasive_abundance"),
    ("tree_seedling_survival", "tree_growth"),
    ("plant_cover_total", "plant_richness"),
    ("seed_germination_emergence", "natural_regeneration"),
    ("carbon_flux", "methane_emissions"),
    ("bird_abundance", "reproductive_success"),
    ("plant_richness", "diversity_indices"),
    ("fish_abundance", "insect_invertebrate"),
]
TIME = "time_since_disturbance"


def main() -> None:
    ctx = make_context()
    tax, rng = ctx.taxonomy, random.Random(SEED)
    counts = study_counts(ctx)
    causes = sorted(c.id for c in tax.of_kind("cause") if c.id != TIME)
    outcomes = sorted(c.id for c in tax.of_kind("outcome"))
    picked: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(c: str, o: str, kind: str) -> bool:
        if (c, o) in seen or c == o:
            return False
        seen.add((c, o))
        picked.append((c, o, kind))
        return True

    for b, k in PER_BAND.items():
        pool = [(c, o) for c in causes for o in outcomes if band(counts.get((c, o), 0)) == b]
        for c, o in rng.sample(pool, min(k, len(pool))):
            add(c, o, "evidence")
    near = []
    for a, b in SIBLINGS:
        for x, y in ((a, b), (b, a)):
            near += [(c, y) for c in causes if counts.get((c, x), 0) >= 2 and (c, y) not in seen]
    for c, o in rng.sample(near, len(near)):
        if sum(k == "near_miss" for *_, k in picked) >= N_NEAR:
            break
        add(c, o, "near_miss")
    for o in rng.sample(outcomes, len(outcomes)):
        if sum(k == "time" for *_, k in picked) >= N_TIME:
            break
        add(TIME, o, "time")
    empty = [(c, o) for c in causes for o in outcomes if counts.get((c, o), 0) == 0]
    for c, o in rng.sample(empty, len(empty)):
        if sum(k == "empty" for *_, k in picked) >= N_EMPTY:
            break
        add(c, o, "empty")
    rng.shuffle(picked)
    rows = []
    for i, (c, o, kind) in enumerate(picked):
        qid = f"C{i + 1:04d}"
        cc, oc = tax.classes[c], tax.classes[o]
        rows.append({"id": qid, "cause_label": cc.label, "cause_description": cc.description or "",
                     "outcome_label": oc.label, "outcome_description": oc.description or "",
                     "paraphrase": int(hashlib.sha1(qid.encode()).hexdigest(), 16) % 2 == 1,
                     "cause_class": c, "outcome_class": o, "kind": kind,
                     "studies": counts.get((c, o), 0)})  # fmt: skip
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    print(json.dumps({"rows": len(rows), "by_kind": kinds, "paraphrase": sum(r["paraphrase"] for r in rows),
                      "path": str(OUT)}))  # fmt: skip


if __name__ == "__main__":
    main()
