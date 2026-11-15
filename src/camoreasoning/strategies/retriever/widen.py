"""`baseline`, then a node-level second pass when the linked sides share no edge (#66).

A side linked to a class reaches only the nodes `node_labels` puts in that class. When the edge the
question asks about has an endpoint outside the linked class ("litter cover" links `soil_fauna` and
`soil_microbial`, the edge's object "Cover of litter" is in no class; "tree sucker density" links
`population_size_trend`, the edge's subject "Slash cover" sits in `mulch_surface_cover`, not the
`prescribed_burning` the cause linked), `baseline` finds no forward edge and the answer is
`no_evidence` although the graph holds the finding.

When `baseline` finds no forward edge, each side is widened with the graph nodes its own words name:
the same node-level IDF match `linker/phrase` uses as its fallback (`PhraseFallbackLinker._nodes`,
close matches only: coverage >= 0.6 and within 0.1 of the best node). A node already on the side keeps
its polarity; a new node takes its qualifier's sign, flipped on the cause side when the cause text names
an ending the node is not (`linker/cessation`). Forward and reversed edges are then recomputed over the
widened sides. A question whose sides still share no edge stays `no_evidence` (D3), and a widened
question that only finds reversed edges stays `no_evidence` with the reversed ids in `searched_for`.
"""

from __future__ import annotations

from camoreasoning.components import Context, Retriever
from camoreasoning.contracts import Candidates, Frame
from camoreasoning.registry import register
from camoreasoning.strategies.linker.baseline import _index
from camoreasoning.strategies.linker.cessation import _node_is_ending, ends_something
from camoreasoning.strategies.linker.phrase import PhraseFallbackLinker
from camoreasoning.strategies.retriever.baseline import side_nodes


def text_nodes(text: str | None, kind: str, ctx: Context) -> dict[str, int]:
    """node_id -> polarity for the graph nodes the side's own words name (empty for no text)."""
    if not text:
        return {}
    side, _ = PhraseFallbackLinker._nodes(text, kind, ctx, _index(ctx))
    flip = kind == "cause" and ends_something(text)
    return {r.id: -r.polarity if flip and not _node_is_ending(r.id, ctx) else r.polarity for r in side.nodes}


@register("retriever", "widen")
class WidenRetriever(Retriever):
    def retrieve(self, frame: Frame, ctx: Context) -> Candidates:
        cause, outcome = side_nodes(frame.cause, ctx), side_nodes(frame.outcome, ctx)
        fwd = ctx.graph.edges_between(set(cause), set(outcome))
        if not fwd:
            cause = {**text_nodes(frame.cause.text, "cause", ctx), **cause}
            outcome = {**text_nodes(frame.outcome.text, "outcome", ctx), **outcome}
            fwd = ctx.graph.edges_between(set(cause), set(outcome))
        seen = set(fwd)
        rev = [e for e in ctx.graph.edges_between(set(outcome), set(cause)) if e not in seen]
        return Candidates(frame, cause, outcome, tuple(fwd), tuple(rev))
