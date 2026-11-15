"""0-call linker: `lexical_v2`, then class-phrase containment, then graph nodes, per question side.

On the gold dev set most missed edges come from a side that links to no class at all: IDF coverage
needs 60% of the side's words, so "mulch application" misses `mulch & surface cover` because
"application" is not a class word. Two fallbacks, tried only when the side has no class:

1. Phrase containment. The class label/synonym phrases the curated node labeller uses (`*` = any word
   ending) are searched inside the side text; the longest matched phrase wins (ties keep every class
   with that length). "mulch application" contains `mulch*`.
2. Graph nodes (NODE_FALLBACK). The baseline's node-level IDF match against node name, entity term and
   measured attribute, restricted to nodes on the right end of an edge. Specific wording ("nestling
   survival", "suspended solids") finds the nodes it names even when no broad class covers it.

A side that `lexical_v2` already linked is left alone, so template questions in class wording link
exactly as before.
"""

from __future__ import annotations

from camoreasoning.components import Context
from camoreasoning.contracts import Ref, Side
from camoreasoning.registry import register
from camoreasoning.strategies.linker.baseline import LexicalLinker
from camoreasoning.strategies.linker.lexical_v2 import PhraseLinker
from camoreasoning.strategies.node_labeler.curated import compile_phrases

NODE_FALLBACK = True
# Node fallback keeps only close matches: within NODE_BAND of the best node's coverage, at least
# NODE_MIN_SCORE, at most NODE_MAX nodes. Loose matches pull in other studies and turn answers "mixed".
NODE_MIN_SCORE = 0.6
NODE_BAND = 0.1
NODE_MAX = 300
PHRASE_SCORE = 0.7  # Ref.score for a containment match (below an exact or full-coverage match)
PHRASE_MARGIN = 0.3


def _contained(text: str, kind: str, ctx: Context) -> list[str]:
    if "linker.phrase" not in ctx.memo:
        ctx.memo["linker.phrase"] = compile_phrases(ctx.taxonomy)
    phrases = ctx.memo["linker.phrase"]
    low = text.lower()
    best: dict[str, int] = {}
    for c in ctx.taxonomy.of_kind(kind):
        n = max((len(p) for p, rx in phrases.get(c.id, ()) if rx.search(low)), default=0)
        if n:
            best[c.id] = n
    if not best:
        return []
    top = max(best.values())
    return sorted(cid for cid, n in best.items() if n == top)


@register("linker", "phrase")
class PhraseFallbackLinker(PhraseLinker):
    def _side(self, text: str | None, kind: str, ctx: Context, ix: dict) -> tuple[Side, float]:
        side, margin = super()._side(text, kind, ctx, ix)
        if ctx.taxonomy.empty or not text or not side.empty:
            return side, margin
        if hits := _contained(text, kind, ctx):
            return Side(text, classes=tuple(Ref(cid, 1, PHRASE_SCORE) for cid in hits)), PHRASE_MARGIN
        if NODE_FALLBACK:
            return self._nodes(text, kind, ctx, ix)
        return side, margin

    @staticmethod
    def _nodes(text: str, kind: str, ctx: Context, ix: dict) -> tuple[Side, float]:
        """Baseline's no-taxonomy path: node-level IDF match (polarity from the node's qualifier)."""
        from camoreasoning.taxonomy import Taxonomy

        bare = Context(ctx.graph, Taxonomy(), ctx.llm, ctx.settings, ctx.out_dir, ctx.memo)
        side, margin = LexicalLinker._side(LexicalLinker(), text, kind, bare, ix)
        if not side.nodes:
            return side, margin
        top = side.nodes[0].score  # ranked best first
        keep = tuple(r for r in side.nodes if r.score >= max(NODE_MIN_SCORE, top - NODE_BAND))[:NODE_MAX]
        return Side(text, nodes=keep), margin
