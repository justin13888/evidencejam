"""Gold labels from the annotate harness (experiments/annotate/gold/merged.jsonl), human rows winning.

Independent by construction: the `gold` task finds candidate edges with its own taxonomy-free lexical
prefilter and a model reads the sentences (decision D5). This module must not read node labels or
engine code (tests/contracts/test_offline.py guards it).
"""

from __future__ import annotations

from collections.abc import Sequence

from camoreasoning.annotate import merged
from camoreasoning.components import Context, GoldLabeler
from camoreasoning.contracts import DevQuestion, GoldItem
from camoreasoning.registry import register


@register("gold_labeler", "annotated")
class AnnotatedGold(GoldLabeler):
    def label(self, items: Sequence[DevQuestion], ctx: Context) -> list[GoldItem]:
        rows = {r["id"]: r for r in merged("gold")}
        out = []
        for it in items:
            r = rows.get(it.id)
            if not r:
                continue
            edges = [x for x in r.get("edges") or [] if x["id"] in ctx.graph.edges]
            tag = "empty" if r["status"] == "no_evidence" else "answerable"
            out.append(GoldItem(
                id=it.id, question=it.question, status=r["status"], direction=r.get("direction"),
                certainty=r.get("certainty"), edge_ids=tuple(x["id"] for x in edges),
                tags=tuple(dict.fromkeys((*it.tags, tag))), split=it.split,
                source=f"human:{r['by']}" if r.get("by") else "llm:annotate",
                edge_effects=tuple((x["id"], x["effect"]) for x in edges),
            ))  # fmt: skip
        return out
