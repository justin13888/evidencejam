"""0-call lexical linker: IDF-weighted token coverage against taxonomy classes, else graph nodes."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

from camoreasoning.components import ClassLinker, Context
from camoreasoning.contracts import Frame, ParsedQuestion, Ref, Side
from camoreasoning.registry import register
from camoreasoning.signs import qualifier_sign
from camoreasoning.strategies.text import tokens

MIN_SCORE = 0.6  # share of the question side's IDF mass a candidate must cover
MAX_NODES = 300
NODE_FIELDS = ("name", "entity_term", "measured_attribute")


def _index(ctx: Context) -> dict:
    if "linker.baseline" not in ctx.memo:
        g, tax = ctx.graph, ctx.taxonomy
        node_toks = {nid: set(tokens(" ".join(str(n.get(f) or "") for f in NODE_FIELDS))) for nid, n in g.nodes.items()}
        class_toks = {c.id: set(tokens(" ".join((c.label, *c.synonyms)))) for c in tax.classes.values()}
        df = Counter(t for ts in node_toks.values() for t in ts)
        n = len(node_toks) or 1
        ctx.memo["linker.baseline"] = {
            "node_toks": node_toks,
            "class_toks": class_toks,
            "idf": {t: math.log(n / c) + 1 for t, c in df.items()},
            "default_idf": math.log(n) + 1,
        }
    return ctx.memo["linker.baseline"]


def _coverage(q: set[str], cand: set[str], idf: dict, default: float) -> float:
    total = sum(idf.get(t, default) for t in q)
    return sum(idf.get(t, default) for t in q & cand) / total if total else 0.0


def _rank(q: set[str], pool: dict[str, set[str]], ix: dict) -> list[tuple[float, str]]:
    scored = ((_coverage(q, toks, ix["idf"], ix["default_idf"]), key) for key, toks in pool.items() if q & toks)
    return sorted((s, k) for s, k in scored if s >= MIN_SCORE)[::-1]


@register("linker", "baseline")
class LexicalLinker(ClassLinker):
    def link(self, batch: Sequence[ParsedQuestion], ctx: Context) -> list[Frame]:
        ix = _index(ctx)
        return [self._frame(p, ctx, ix) for p in batch]

    def _side(self, text: str | None, kind: str, ctx: Context, ix: dict) -> tuple[Side, float]:
        q = set(tokens(text))
        if not q:
            return Side(text), 0.0
        if not ctx.taxonomy.empty:
            pool = {c.id: ix["class_toks"][c.id] for c in ctx.taxonomy.of_kind(kind)}
            ranked = _rank(q, pool, ix)
            margin = ranked[0][0] - (ranked[1][0] if len(ranked) > 1 else 0.0) if ranked else 0.0
            top = [(s, k) for s, k in ranked if s >= ranked[0][0] - 1e-9] if ranked else []
            return Side(text, classes=tuple(Ref(k, 1, round(s, 4)) for s, k in top)), margin
        g = ctx.graph
        has = g.out_edges if kind == "cause" else g.in_edges
        pool = {nid: ix["node_toks"][nid] for nid in has}
        ranked = _rank(q, pool, ix)[:MAX_NODES]
        refs = []
        for s, nid in ranked:
            pol = qualifier_sign(g.nodes[nid].get("state_or_change_qualifier"))
            refs.append(Ref(nid, 0 if pol is None else pol, round(s, 4)))
        return Side(text, nodes=tuple(refs)), (ranked[0][0] if ranked else 0.0)

    def _frame(self, p: ParsedQuestion, ctx: Context, ix: dict) -> Frame:
        cause, m1 = self._side(p.cause_text, "cause", ctx, ix)
        outcome, m2 = self._side(p.outcome_text, "outcome", ctx, ix)
        via = "lexical" if not (cause.empty or outcome.empty) else "none"
        return Frame(p, cause, outcome, via, round(min(m1, m2), 4))
