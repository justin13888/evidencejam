"""Dev questions written by a model from graph seeds, independent of our taxonomy (decision D5).

Source: experiments/annotate/questions/merged.jsonl ({id, cause, outcome, _meta: {hint_tags, seed_edge|pair}}).
Question = the hidden-set template. ~20% holdout by id hash. Tags = mechanical trap hints from the seed.
"""

from __future__ import annotations

import hashlib

from camoreasoning.annotate import merged
from camoreasoning.components import Context, DevsetBuilder
from camoreasoning.contracts import DevQuestion
from camoreasoning.registry import register
from camoreasoning.taxonomy import Taxonomy

TEMPLATE = "What effect does {cause} have on {outcome}?"


def split_of(qid: str) -> str:
    return "holdout" if int(hashlib.sha1(qid.encode()).hexdigest(), 16) % 5 == 0 else "dev"


@register("devset_builder", "annotated")
class AnnotatedQuestions(DevsetBuilder):
    def build(self, taxonomy: Taxonomy, ctx: Context) -> list[DevQuestion]:
        out, seen = [], set()
        for row in merged("questions"):
            q = TEMPLATE.format(cause=row["cause"].strip(), outcome=row["outcome"].strip())
            if q.lower() in seen:
                continue
            seen.add(q.lower())
            meta = row.get("_meta") or {}
            out.append(DevQuestion(id=f"D-{row['id']}", question=q, tags=tuple(meta.get("hint_tags") or ()),
                                   split=split_of(row["id"]), meta=meta))  # fmt: skip
        return out
