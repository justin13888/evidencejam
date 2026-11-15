"""Class-level gold labels from the annotate harness (experiments/annotate/class_gold/merged.jsonl).

Same rubric and provenance rules as `annotated`. The labeller judged every candidate from its sentence
without seeing whether the taxonomy-free lexical pool or the nomination list offered it. Items whose
included edges came only from nomination are tagged `recall:engine`. This module reads no taxonomy.
"""

from __future__ import annotations

from collections.abc import Sequence

from camoreasoning.annotate import merged
from camoreasoning.components import Context, GoldLabeler
from camoreasoning.contracts import DevQuestion, GoldItem
from camoreasoning.registry import register
from camoreasoning.strategies.gold_labeler.annotated import _source


@register("gold_labeler", "class_annotated")
class ClassAnnotatedGold(GoldLabeler):
    def label(self, items: Sequence[DevQuestion], ctx: Context) -> list[GoldItem]:
        rows = {r["id"]: r for r in merged("class_gold")}
        out = []
        for it in items:
            r = rows.get(it.id)
            if not r:
                continue
            meta = r.get("_meta") or {}
            ref_of = {eid: ref for ref, eid in (meta.get("refs") or {}).items()}
            edges = [x for x in r.get("edges") or [] if x["id"] in ctx.graph.edges]
            src = {(meta.get("source") or {}).get(ref_of.get(x["id"]), "pool") for x in edges}
            tags = [*it.tags, "empty" if r["status"] == "no_evidence" else "answerable"]
            tags += ["recall:engine"] if "nominated" in src else []
            out.append(GoldItem(
                id=it.id, question=it.question, status=r["status"], direction=r.get("direction"),
                certainty=r.get("certainty"), edge_ids=tuple(x["id"] for x in edges),
                tags=tuple(dict.fromkeys(tags)), split=it.split, source=_source(r.get("by")),
                edge_effects=tuple((x["id"], x["effect"]) for x in edges),
            ))  # fmt: skip
        return out
