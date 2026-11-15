"""Class-level dev questions, worded like the hidden set (issue #9 audit).

Source: experiments/annotate/class_questions/merged.jsonl. Seeds are taxonomy class pairs
(experiments/devsets/class_seeds.py); a labeller wrote the wording (exact label or paraphrase) and its own
search terms. Question = the hidden-set template. Holdout = the same sha1 split as `annotated`.

meta.nominated lists the edges our taxonomy places between the two classes, in either direction. It only
widens the candidate pool `class_gold` shows the gold labeller (who never sees where an edge came from);
it never sets a label.
"""

from __future__ import annotations

from camoreasoning.annotate import merged
from camoreasoning.components import Context, DevsetBuilder
from camoreasoning.contracts import DevQuestion
from camoreasoning.registry import register
from camoreasoning.strategies.devset_builder.annotated import TEMPLATE, split_of
from camoreasoning.taxonomy import Taxonomy

KIND_TAGS = {"near_miss": "trap:near_miss_classes", "time": "trap:time_as_cause"}


@register("devset_builder", "classlevel")
class ClassLevelQuestions(DevsetBuilder):
    def build(self, taxonomy: Taxonomy, ctx: Context) -> list[DevQuestion]:
        def nodes(cid: str) -> set[str]:
            return {lb.node_id for lb in taxonomy.nodes_of(cid)} if cid in taxonomy.classes else set()

        out, seen = [], set()
        for row in merged("class_questions"):
            q = TEMPLATE.format(cause=row["cause"].strip(), outcome=row["outcome"].strip())
            if q.lower() in seen:
                continue
            seen.add(q.lower())
            m = row.get("_meta") or {}
            c, o = nodes(m.get("cause_class", "")), nodes(m.get("outcome_class", ""))
            pairs = set(ctx.graph.edges_between(c, o)) | set(ctx.graph.edges_between(o, c)) if c and o else set()
            nominated = sorted(pairs)
            kind = m.get("kind", "")
            tags = ("class", f"seed:{kind}" if kind else "", *([KIND_TAGS[kind]] if kind in KIND_TAGS else []))
            meta = {**m, "cause_terms": row["cause_terms"], "outcome_terms": row["outcome_terms"],
                    "nominated": nominated}  # fmt: skip
            out.append(DevQuestion(id=f"C-{row['id']}", question=q, tags=tuple(t for t in tags if t),
                                   split=split_of(row["id"]), meta=meta))  # fmt: skip
        return out
