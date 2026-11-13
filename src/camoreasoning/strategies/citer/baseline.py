"""Cite every included vote's edge (graph order), capped."""

from __future__ import annotations

from camoreasoning.components import Citer, Context
from camoreasoning.contracts import Verdict
from camoreasoning.registry import register

CAP = 25


@register("citer", "baseline")
class IncludedEdges(Citer):
    def cite(self, verdict: Verdict, ctx: Context) -> list[str]:
        return list(dict.fromkeys(v.edge_id for v in verdict.included))[:CAP]
