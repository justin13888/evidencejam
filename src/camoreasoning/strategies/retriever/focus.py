"""`widen`, then each class-linked side narrowed to the nodes its extra words name (#66).

A side links a class through some of its words, and the class brings every node `node_labels` puts in
it. Words the class does not cover are the part of the question the class cannot see:
"ericaceous shrub cover" links `plant_cover_total` through "shrub cover", and the class also holds
bare ground, tree and herb cover, whose edges outvote the ericaceous ones and turn the answer `mixed`.

Per side, after `widen`: the side's extra words are its tokens (`text.tokens`) that no linked class's
label or synonyms contain. When there are some, the side's focus is the nodes whose name, entity term
or measured attribute holds one of them (a word stem of FOCUS_STEM characters, so "abandonment"
meets "abandoned"). If the forward edges restricted to that focus are not empty, they replace the
forward edges; otherwise the side is left whole. The cause side is narrowed first, then the outcome.
A side that links an exact class label or synonym has no extra words, so template questions in class
wording are retrieved exactly as `widen` retrieves them. Reversed edges are recomputed over the
narrowed sides.
"""

from __future__ import annotations

from camoreasoning.components import Context
from camoreasoning.contracts import Candidates, Frame, Side
from camoreasoning.registry import register
from camoreasoning.strategies.linker.baseline import _index
from camoreasoning.strategies.retriever.widen import WidenRetriever
from camoreasoning.strategies.text import tokens

FOCUS_STEM = 6


def _stems(words) -> set[str]:
    return {w[:FOCUS_STEM] for w in words}


def extra_words(side: Side, ctx: Context) -> set[str]:
    """The side's word stems that none of its linked classes' label/synonym words cover."""
    if not side.classes or not side.text:
        return set()
    ix = _index(ctx)
    covered = _stems(t for r in side.classes for t in ix["class_toks"].get(r.id, ()))
    return _stems(tokens(side.text)) - covered


def focus(nodes: dict[str, int], words: set[str], ctx: Context) -> dict[str, int]:
    """The side's nodes whose own words hold one of `words` (as stems)."""
    if not words:
        return {}
    ix = _index(ctx)
    return {n: p for n, p in nodes.items() if _stems(ix["node_toks"].get(n, ())) & words}


@register("retriever", "focus")
class FocusRetriever(WidenRetriever):
    def retrieve(self, frame: Frame, ctx: Context) -> Candidates:
        c = super().retrieve(frame, ctx)
        cause, outcome, fwd = dict(c.cause_nodes), dict(c.outcome_nodes), list(c.forward)
        if not fwd:
            return c
        for side, kind in ((frame.cause, "cause"), (frame.outcome, "outcome")):
            nodes = cause if kind == "cause" else outcome
            narrow = focus(nodes, extra_words(side, ctx), ctx)
            if not narrow:
                continue
            key = "subject" if kind == "cause" else "object"
            kept = [e for e in fwd if ctx.graph.edges[e][key] in narrow]
            if kept:
                fwd = kept
                if kind == "cause":
                    cause = narrow
                else:
                    outcome = narrow
        if fwd == list(c.forward):
            return c
        seen = set(fwd)
        rev = [e for e in ctx.graph.edges_between(set(outcome), set(cause)) if e not in seen]
        return Candidates(frame, cause, outcome, tuple(fwd), tuple(rev))
