"""0-call linker: `phrase`, plus question negation for a cause that ends something (#61).

A cause worded as the end of something ("cessation of synthetic estrogen addition", "abandonment of
peat harvesting") asks about the opposite of the class it links to: `contaminant_exposure` and
`peat_extraction` are the things that stop. `phrase` links those sides at polarity +1, so the engine
reads the effect of adding estrogen or harvesting peat. Here each cause Ref is flipped (-1 x its
polarity) when all of these hold:

1. The cause text names an ending (CUE: cessation, abandonment, closure, removal, stopping, halting,
   discontinuation, withdrawal, elimination).
2. The cue is not after "since", "after" or "following": "time since road abandonment" is elapsed
   time, which `time_since_disturbance` already means.
3. The class or node is not itself an ending: none of its label/synonym phrases (or, for a node, its
   entity term) contain a cue. A node's name is not checked: it repeats the node's qualifier,
   which already set the Ref's polarity. "invasive fish removal" links `invasive species removal`,
   which already is the removal, and "vegetation removal" links `mechanical vegetation control`
   through its synonym "vegetation removal".

The outcome side is left alone. The engine applies the flip the same way it does for a node-level
removal (tests/strategies/test_traps.py::test_asking_about_the_removal_flips_back).
"""

from __future__ import annotations

import re

from camoreasoning.components import Context
from camoreasoning.contracts import Ref, Side
from camoreasoning.registry import register
from camoreasoning.strategies.linker.phrase import PhraseFallbackLinker

CUE = re.compile(
    r"\b(cessation|ceas(?:e|ed|es|ing)|abandon(?:ed|ing|ment)?|clos(?:ure|ing)|remov(?:al|ed|ing)|"
    r"stop(?:ped|ping)?|halt(?:ed|ing)?|discontinu\w*|withdraw(?:al|n)?|eliminat(?:e|ed|ing|ion))\b",
    re.I,
)
ELAPSED = re.compile(r"\b(since|after|following)\b", re.I)


def ends_something(text: str | None) -> bool:
    """The side's text names an ending that is not a point in elapsed time."""
    m = CUE.search(text or "")
    return bool(m) and not ELAPSED.search(text[: m.start()])


def _class_is_ending(cid: str, ctx: Context) -> bool:
    c = ctx.taxonomy.classes[cid]
    return any(CUE.search(p) for p in (c.label, *c.synonyms))


def _node_is_ending(nid: str, ctx: Context) -> bool:
    # entity_term only: a node's `name` repeats its state_or_change_qualifier ("Removal of protective
    # tree cover", qualifier "removed"), which already set the Ref's polarity to -1 (D-Q0015).
    return bool(CUE.search(str(ctx.graph.nodes.get(nid, {}).get("entity_term") or "")))


def _flip(refs: tuple[Ref, ...], is_ending) -> tuple[Ref, ...]:
    return tuple(r if is_ending(r.id) else Ref(r.id, -r.polarity, r.score) for r in refs)


@register("linker", "cessation")
class CessationLinker(PhraseFallbackLinker):
    def _side(self, text: str | None, kind: str, ctx: Context, ix: dict) -> tuple[Side, float]:
        side, margin = super()._side(text, kind, ctx, ix)
        if kind != "cause" or side.empty or not ends_something(text):
            return side, margin
        classes = _flip(side.classes, lambda cid: _class_is_ending(cid, ctx))
        nodes = _flip(side.nodes, lambda nid: _node_is_ending(nid, ctx))
        return Side(side.text, classes=classes, nodes=nodes), margin
