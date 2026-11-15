"""0-call linker: `cessation`, plus static word embeddings for a side that links to nothing (ROADMAP 24).

Measured, not recommended (ROADMAP 24): on an independent reworded probe it fixed 1 empty side and
linked 6 wrongly. Kept for the record. The vectors file is not committed: build it with
experiments/embeddings/build_vectors.py. Without it, this linker is exactly `cessation`.

Every lexical step (class phrases, containment, graph nodes, word stems) needs a shared word. A judge
who types a synonym with none ("global heating", "clear-felling", "seedling guards") gets an empty side
and a no_evidence answer. Here, only for such a side:

1. The side's vector is the IDF-weighted mean of its words' GloVe vectors (taxonomy/word_vectors.bin.gz,
   built offline by experiments/embeddings/build_vectors.py), centred on the vocabulary mean: raw GloVe
   phrase means share one direction, so unrelated phrases score 0.6-0.8. Unknown words are skipped.
2. Each class of the side's kind is scored by its best cosine over its phrases: the label, its parts
   split on "&", "/", ",", "(" and its synonyms.
3. The best class links if its cosine is at least MIN_COS and beats the runner-up by MIN_GAP. The gap
   does the work (experiments/embeddings/tune_embed.py): at 0.02, 6 of 9 dev empty sides linked a wrong
   class; at 0.1, none does, and the synonym probe keeps 18 of 28 by embedding alone.
   A cause that names an ending is flipped as in `cessation`.

Sides any lexical step linked are untouched, so answers change only where the default had nothing.
A frame with an embedding-linked side reports via = "embedding". The vectors are read from the active
taxonomy directory.
Pure Python, no numpy: it runs only for empty sides, scoring ~81 classes x ~10 phrases x 100 dims.
"""

from __future__ import annotations

import gzip
import math
import re
import struct
from array import array
from dataclasses import replace

from camoreasoning.components import Context
from camoreasoning.config import TAXONOMY_DIR
from camoreasoning.contracts import Frame, ParsedQuestion, Ref, Side
from camoreasoning.registry import register
from camoreasoning.strategies.linker.baseline import _index
from camoreasoning.strategies.linker.cessation import CessationLinker, _class_is_ending, ends_something
from camoreasoning.strategies.text import STOP, tokens

VECTORS = "word_vectors.bin.gz"  # inside the active taxonomy directory
MIN_COS = 0.5  # centred cosine a class needs to link an otherwise empty side
MIN_GAP = 0.1  # and its lead over the runner-up (tuned so no dev empty side links wrong)
EMBED_SCORE = 0.4  # Ref score: weaker than any lexical link
CENTER = True  # subtract the vocabulary's mean vector ("<mean>" in the file) before comparing
MEAN = "<mean>"


def _load(ctx: Context) -> dict[str, tuple[float, bytes]] | None:
    path = (ctx.settings.taxonomy_dir or TAXONOMY_DIR) / VECTORS
    if not path.exists():
        return None
    raw = gzip.decompress(path.read_bytes())
    assert raw[:4] == b"WV1\n", "bad word vector file"
    n, dim = struct.unpack_from("<II", raw, 4)
    out, at = {}, 12
    for _ in range(n):
        (ln,) = struct.unpack_from("<H", raw, at)
        word = raw[at + 2 : at + 2 + ln].decode("utf-8")
        at += 2 + ln
        (scale,) = struct.unpack_from("<f", raw, at)
        out[word] = (scale, raw[at + 4 : at + 4 + dim])
        at += 4 + dim
    return out


def _raw(hit: tuple[float, bytes]) -> array:
    scale, q = hit
    return array("f", (scale * x for x in array("b", q)))


def _vec(word: str, vecs: dict) -> array | None:
    hit = vecs.get(word) or (vecs.get(word[:-1]) if word.endswith("s") else None)
    if hit is None or word == MEAN:
        return None
    v = _raw(hit)
    if CENTER and MEAN in vecs:
        v = array("f", (a - b for a, b in zip(v, _raw(vecs[MEAN]), strict=True)))
    return v


def phrase_vector(text: str, ctx: Context) -> array | None:
    """IDF-weighted mean of known word vectors, unit length; None if no word is known."""
    st = _state(ctx)
    if st is None:
        return None
    ix = _index(ctx)
    acc = None
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if w in STOP or len(w) < 2:
            continue
        v = _vec(w, st["vecs"])
        if v is None:
            continue
        t = tokens(w)
        wt = ix["idf"].get(t[0], ix["default_idf"]) if t else 1.0
        acc = array("f", (wt * x for x in v)) if acc is None else array("f", (a + wt * x for a, x in zip(acc, v)))
    if acc is None:
        return None
    norm = math.sqrt(sum(x * x for x in acc)) or 1.0
    return array("f", (x / norm for x in acc))


def _parts(label: str) -> list[str]:
    return [label] + [p.strip() for p in re.split(r"[&/,()]", label) if p.strip() and p.strip() != label]


def _state(ctx: Context) -> dict | None:
    key = "linker.embed"
    if key not in ctx.memo:
        vecs = _load(ctx)
        ctx.memo[key] = None if vecs is None else {"vecs": vecs, "classes": None, "linked": set()}
    return ctx.memo[key]


def _class_vectors(ctx: Context) -> dict[str, list[array]]:
    st = _state(ctx)
    if st["classes"] is None:
        st["classes"] = {}
        for c in ctx.taxonomy.classes.values():
            phrases = _parts(c.label) + [s.replace("*", "") for s in c.synonyms]
            st["classes"][c.id] = [v for p in phrases if (v := phrase_vector(p, ctx)) is not None]
    return st["classes"]


def nearest(text: str, kind: str, ctx: Context) -> list[tuple[float, str]]:
    """[(cosine, class id)] of this kind, best first."""
    q = phrase_vector(text, ctx)
    if q is None:
        return []
    cv = _class_vectors(ctx)
    scored = []
    for c in ctx.taxonomy.of_kind(kind):
        if cv.get(c.id):
            scored.append((max(sum(a * b for a, b in zip(q, v)) for v in cv[c.id]), c.id))
    return sorted(scored, reverse=True)


@register("linker", "embed")
class EmbedLinker(CessationLinker):
    def _frame(self, p: ParsedQuestion, ctx: Context, ix: dict) -> Frame:
        frame = super()._frame(p, ctx, ix)
        st = _state(ctx)
        if frame.via == "lexical" and st and {(p.cause_text, "cause"), (p.outcome_text, "outcome")} & st["linked"]:
            return replace(frame, via="embedding")
        return frame

    def _side(self, text: str | None, kind: str, ctx: Context, ix: dict) -> tuple[Side, float]:
        side, margin = super()._side(text, kind, ctx, ix)
        if not side.empty or not text or ctx.taxonomy.empty or _state(ctx) is None:
            return side, margin
        ranked = nearest(text, kind, ctx)
        if not ranked or ranked[0][0] < MIN_COS:
            return side, margin
        gap = ranked[0][0] - (ranked[1][0] if len(ranked) > 1 else 0.0)
        if gap < MIN_GAP:
            return side, margin
        cid = ranked[0][1]
        pol = -1 if kind == "cause" and ends_something(text) and not _class_is_ending(cid, ctx) else 1
        _state(ctx)["linked"].add((text, kind))
        return Side(text, classes=(Ref(cid, pol, EMBED_SCORE),)), round(gap, 4)
