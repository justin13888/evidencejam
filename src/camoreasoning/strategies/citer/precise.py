"""Precision-first citer: cite only included votes that agree with the verdict, one per twin sentence.

- increase/decrease/no_effect: keep included votes whose effect matches (+1/-1/0).
- mixed/unclear: keep every included vote with a sign (both sides bear on the question).
- Twins (same document, same `original_sentence`, same effect) collapse to the first in graph order;
  twins with different effects are both kept.
- Order: document (first appearance among votes), then certainty grade (strongest first), then vote order.
- Nothing left: fall back to all included edges so "non-empty iff answered" holds. 0 LLM calls.
"""

from __future__ import annotations

from camoreasoning.components import Citer, Context
from camoreasoning.contracts import EdgeVote, Verdict
from camoreasoning.registry import register
from camoreasoning.schema import CERTAINTY_ORDER

CAP = 25
EFFECT = {"increase": 1, "decrease": -1, "no_effect": 0}


def _keep(verdict: Verdict) -> list[EdgeVote]:
    want = EFFECT.get(verdict.direction or "")
    if want is None:
        return [v for v in verdict.included if v.effect is not None]
    return [v for v in verdict.included if v.effect == want]


def _dedupe_twins(votes: list[EdgeVote], ctx: Context) -> list[EdgeVote]:
    order = ctx.graph.meta.get("order", {})
    best: dict[tuple, EdgeVote] = {}
    seen: set[str] = set()
    out: list[EdgeVote] = []
    for v in votes:
        if v.edge_id in seen:
            continue
        seen.add(v.edge_id)
        e = ctx.graph.edges.get(v.edge_id, {})
        sentence = (e.get("original_sentence") or "").strip()
        if not sentence:
            out.append(v)
            continue
        key = (e.get("source_document", v.doc_id), sentence, v.effect)
        cur = best.get(key)
        if cur is None:
            best[key] = v
            out.append(v)
        elif order.get(v.edge_id, 1 << 30) < order.get(cur.edge_id, 1 << 30):
            out[out.index(cur)] = v  # keep the twin earliest in graph order, at the first twin's slot
            best[key] = v
    return out


@register("citer", "precise")
class PreciseCiter(Citer):
    def cite(self, verdict: Verdict, ctx: Context) -> list[str]:
        if verdict.status != "answered":
            return []
        kept = _dedupe_twins(_keep(verdict), ctx)
        if not kept:
            return list(dict.fromkeys(v.edge_id for v in verdict.included))[:CAP]
        doc_rank: dict[str, int] = {}
        for v in verdict.votes:
            doc_rank.setdefault(v.doc_id, len(doc_rank))
        pos = {v.edge_id: i for i, v in reversed(list(enumerate(verdict.votes)))}
        kept.sort(key=lambda v: (doc_rank[v.doc_id], -CERTAINTY_ORDER.get(v.certainty_grade or "", -1), pos[v.edge_id]))
        return [v.edge_id for v in kept][:CAP]
