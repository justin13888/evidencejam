"""0-call lexical linker with phrase tie-breaking on top of `baseline`.

Rules, applied per question side against taxonomy classes of that kind:
1. Exact phrase: if the side's text equals a class label or synonym (after `tokens()` normalisation,
   `*` = any suffix on the last word), those classes win outright. If several match, classes whose
   label matches beat those matched only by a synonym.
2. Otherwise use baseline's IDF coverage ranking. When several classes tie at the top, keep those whose
   longest label/synonym phrase found word-for-word in the text is longest.
3. With no taxonomy, behave exactly like baseline (graph-node matching).
"""

from __future__ import annotations

from camoreasoning.components import Context
from camoreasoning.contracts import Ref, Side
from camoreasoning.registry import register
from camoreasoning.strategies.linker.baseline import LexicalLinker, _rank
from camoreasoning.strategies.text import tokens

EXACT_MARGIN = 1.0  # an exact phrase hit is as confident as the linker gets


def _phrases(ctx: Context) -> dict[str, list[tuple[tuple[str, ...], bool, bool]]]:
    """class id -> [(phrase tokens, is_label, wildcard)], built once per run."""
    if "linker.lexical_v2" not in ctx.memo:
        out = {}
        for c in ctx.taxonomy.classes.values():
            items = [(tuple(tokens(c.label)), True, False)]
            items += [(tuple(tokens(s.replace("*", ""))), False, s.endswith("*")) for s in c.synonyms]
            out[c.id] = [(p, lab, wild) for p, lab, wild in items if p]
        ctx.memo["linker.lexical_v2"] = out
    return ctx.memo["linker.lexical_v2"]


def _equal(text: tuple[str, ...], phrase: tuple[str, ...], wildcard: bool) -> bool:
    if not wildcard:
        return text == phrase
    return len(text) == len(phrase) and text[:-1] == phrase[:-1] and text[-1].startswith(phrase[-1])


def _longest_contained(text: tuple[str, ...], phrases) -> int:
    best = 0
    for p, _, _ in phrases:
        n = len(p)
        if n > best and any(text[i : i + n] == p for i in range(len(text) - n + 1)):
            best = n
    return best


@register("linker", "lexical_v2")
class PhraseLinker(LexicalLinker):
    def _side(self, text: str | None, kind: str, ctx: Context, ix: dict) -> tuple[Side, float]:
        if ctx.taxonomy.empty:
            return super()._side(text, kind, ctx, ix)
        q = tuple(tokens(text))
        if not q:
            return Side(text), 0.0
        phrases = _phrases(ctx)
        kind_ids = [c.id for c in ctx.taxonomy.of_kind(kind)]

        exact = {cid: any(lab for p, lab, w in phrases[cid] if _equal(q, p, w)) for cid in kind_ids
                 if any(_equal(q, p, w) for p, _, w in phrases[cid])}  # fmt: skip
        if exact:
            by_label = [cid for cid, lab in exact.items() if lab]
            chosen = by_label or list(exact)
            return Side(text, classes=tuple(Ref(cid, 1, 1.0) for cid in sorted(chosen))), EXACT_MARGIN

        pool = {cid: ix["class_toks"][cid] for cid in kind_ids}
        ranked = _rank(set(q), pool, ix)
        if not ranked:
            return Side(text), 0.0
        top_score = ranked[0][0]
        top = [k for s, k in ranked if s >= top_score - 1e-9]
        if len(top) > 1:
            lengths = {k: _longest_contained(q, phrases[k]) for k in top}
            best = max(lengths.values())
            if best:
                top = [k for k in top if lengths[k] == best]
        runner_up = next((s for s, k in ranked if k not in top), 0.0)
        margin = top_score - runner_up if len(top) == 1 else 0.0
        return Side(text, classes=tuple(Ref(k, 1, round(top_score, 4)) for k in sorted(top))), margin
