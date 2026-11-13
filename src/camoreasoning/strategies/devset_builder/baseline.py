"""Template questions over cause x outcome class pairs: ~2/3 with edges, ~1/3 without; every 5th
item goes to holdout. Deterministic. Trap tagging is left to better builders."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from camoreasoning.components import Context, DevsetBuilder
from camoreasoning.contracts import DevQuestion
from camoreasoning.registry import register
from camoreasoning.taxonomy import Taxonomy

N_ITEMS = 90


def _h(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


@register("devset_builder", "baseline")
class PairTemplates(DevsetBuilder):
    def build(self, taxonomy: Taxonomy, ctx: Context) -> list[DevQuestion]:
        if taxonomy.empty:
            return []
        linked: dict[tuple[str, str], int] = defaultdict(int)
        for e in ctx.graph.edges.values():
            for s in taxonomy.classes_of(e["subject"]):
                for o in taxonomy.classes_of(e["object"]):
                    linked[(s.class_id, o.class_id)] += 1
        pairs = [(c, o) for c in taxonomy.of_kind("cause") for o in taxonomy.of_kind("outcome") if c.id != o.id]
        pairs.sort(key=lambda p: _h(p[0].id + "|" + p[1].id))
        full = [p for p in pairs if linked[(p[0].id, p[1].id)]][: N_ITEMS * 2 // 3]
        empty = [p for p in pairs if not linked[(p[0].id, p[1].id)]][: N_ITEMS - len(full)]
        items = []
        for i, (c, o) in enumerate(sorted(full + empty, key=lambda p: _h(p[1].id + p[0].id))):
            tag = "answerable" if linked[(c.id, o.id)] else "empty"
            items.append(DevQuestion(
                id=f"D-{i + 1:03d}",
                question=f"What effect does {c.label.lower()} have on {o.label.lower()}?",
                tags=(tag,),
                split="holdout" if i % 5 == 4 else "dev",
                meta={"cause": c.id, "outcome": o.id},
            ))  # fmt: skip
        return items
