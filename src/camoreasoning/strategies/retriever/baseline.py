"""Expand classes to labelled nodes; forward = cause->outcome edges, reversed = outcome->cause."""

from __future__ import annotations

from camoreasoning.components import Context, Retriever
from camoreasoning.contracts import Candidates, Frame, Side
from camoreasoning.registry import register


def side_nodes(side: Side, ctx: Context) -> dict[str, int]:
    """node_id -> polarity relative to the question side (first match wins)."""
    out: dict[str, int] = {}
    for ref in side.classes:
        for lb in ctx.taxonomy.nodes_of(ref.id):
            out.setdefault(lb.node_id, ref.polarity * lb.polarity)
    for ref in side.nodes:
        out.setdefault(ref.id, ref.polarity)
    return out


@register("retriever", "baseline")
class DirectRetriever(Retriever):
    def retrieve(self, frame: Frame, ctx: Context) -> Candidates:
        cause, outcome = side_nodes(frame.cause, ctx), side_nodes(frame.outcome, ctx)
        fwd = ctx.graph.edges_between(set(cause), set(outcome))
        seen = set(fwd)
        rev = [e for e in ctx.graph.edges_between(set(outcome), set(cause)) if e not in seen]
        return Candidates(frame, cause, outcome, tuple(fwd), tuple(rev))
