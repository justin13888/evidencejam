"""0-call linker: `lexical_v2`, then class-phrase containment, then graph nodes plus word stems.

On the gold dev set most missed edges come from a side that links to no class at all: IDF coverage
needs 60% of the side's words, so "mulch application" misses `mulch & surface cover` because
"application" is not a class word. Fallbacks, tried only when the side has no class:

1. Phrase containment. The class label/synonym phrases the curated node labeller uses (`*` = any word
   ending) are searched inside the side text; the longest matched phrase wins (ties keep every class
   with that length). "mulch application" contains `mulch*`.
2. Graph nodes (NODE_FALLBACK). The baseline's node-level IDF match against node name, entity term and
   measured attribute, restricted to nodes on the right end of an edge. Specific wording ("nestling
   survival", "suspended solids") finds the nodes it names even when no broad class covers it.
3. Word stems (STEM_FALLBACK), alongside step 2. IDF coverage again, but over words cut to STEM_LEN
   characters, so inflected wording ("inoculating soil", "restoring wetlands") reaches its class.
   The side keeps both the stem-matched classes and the step-2 nodes: either alone misses edges the
   other finds.

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
from camoreasoning.strategies.text import tokens

NODE_FALLBACK = True
# Node fallback keeps only close matches: within NODE_BAND of the best node's coverage, at least
# NODE_MIN_SCORE, at most NODE_MAX nodes. Loose matches pull in other studies and turn answers "mixed".
NODE_MIN_SCORE = 0.6
NODE_BAND = 0.1
NODE_MAX = 300
PHRASE_SCORE = 0.7  # Ref.score for a containment match (below an exact or full-coverage match)
PHRASE_MARGIN = 0.3
# Stem fallback: words cut to STEM_LEN characters, so "inoculating" meets `inoculation` and "restoring
# wetlands" meets `wetland restoration`. A class must cover STEM_MIN_SCORE of the side's IDF mass.
# On class dev, 5 and 6 tie on recall; 6 keeps edge precision and node-level dev accuracy.
STEM_FALLBACK = True
STEM_LEN = 6
STEM_MIN_SCORE = 0.5
STEM_SCORE = 0.6  # Ref.score for a stem match (below a containment match)


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


def _stem(t: str) -> str:
    return t[:STEM_LEN]


def _stemmed(text: str, kind: str, ctx: Context, ix: dict) -> tuple[list[str], float]:
    """Classes whose label/synonym word stems cover >= STEM_MIN_SCORE of the side's IDF mass."""
    if "linker.phrase.stems" not in ctx.memo:
        idf, default = ix["idf"], ix["default_idf"]
        stem_idf: dict[str, float] = {}
        for t, w in idf.items():  # a stem is as rare as its rarest word
            s = _stem(t)
            stem_idf[s] = max(stem_idf.get(s, 0.0), w)
        ctx.memo["linker.phrase.stems"] = (
            stem_idf,
            default,
            {cid: {_stem(t) for t in toks} for cid, toks in ix["class_toks"].items()},
        )
    stem_idf, default, class_stems = ctx.memo["linker.phrase.stems"]
    q = {_stem(t) for t in tokens(text)}
    total = sum(stem_idf.get(s, default) for s in q)
    if not total:
        return [], 0.0
    scored = []
    for c in ctx.taxonomy.of_kind(kind):
        hit = q & class_stems[c.id]
        if hit:
            scored.append((sum(stem_idf.get(s, default) for s in hit) / total, c.id))
    scored = sorted(s for s in scored if s[0] >= STEM_MIN_SCORE)[::-1]
    if not scored:
        return [], 0.0
    top = scored[0][0]
    runner = next((s for s, _ in scored if s < top - 1e-9), 0.0)
    return sorted(k for s, k in scored if s >= top - 1e-9), top - runner


@register("linker", "phrase")
class PhraseFallbackLinker(PhraseLinker):
    def _side(self, text: str | None, kind: str, ctx: Context, ix: dict) -> tuple[Side, float]:
        side, margin = super()._side(text, kind, ctx, ix)
        if ctx.taxonomy.empty or not text or not side.empty:
            return side, margin
        if hits := _contained(text, kind, ctx):
            return Side(text, classes=tuple(Ref(cid, 1, PHRASE_SCORE) for cid in hits)), PHRASE_MARGIN
        if NODE_FALLBACK:
            side, margin = self._nodes(text, kind, ctx, ix)
        if STEM_FALLBACK and (stems := _stemmed(text, kind, ctx, ix))[0]:
            hits, stem_margin = stems
            classes = tuple(Ref(cid, 1, STEM_SCORE) for cid in hits)
            return Side(text, classes=classes, nodes=side.nodes), min(stem_margin, PHRASE_MARGIN)
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
