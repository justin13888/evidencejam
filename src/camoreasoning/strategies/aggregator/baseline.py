"""One vote per document (majority within doc), then >=2/3 of documents agree (decision D2), else mixed."""

from __future__ import annotations

from collections import Counter, defaultdict

from camoreasoning.components import Aggregator, Context
from camoreasoning.contracts import Candidates, EdgeVote, Verdict
from camoreasoning.registry import register

AGREE = 2 / 3  # decision D2 (ROADMAP "Decisions"); matches the gold rubric
NAMES = {1: "increase", -1: "decrease", 0: "no_effect"}


def doc_effect(effects: list[int]) -> int | None:
    c = Counter(effects).most_common()
    return None if len(c) > 1 and c[0][1] == c[1][1] else c[0][0]


@register("aggregator", "baseline")
class DocMajority(Aggregator):
    def aggregate(self, votes: tuple[EdgeVote, ...], candidates: Candidates, ctx: Context) -> Verdict:
        by_doc: dict[str, list[int]] = defaultdict(list)
        for v in votes:
            if v.included and v.effect is not None:
                by_doc[v.doc_id].append(v.effect)
        if not any(v.included for v in votes):
            return Verdict("no_evidence", None, votes)
        docs = tuple((d, doc_effect(es)) for d, es in sorted(by_doc.items()))
        signed = [e for _, e in docs if e is not None]
        if not signed:
            return Verdict("answered", "unclear", votes, docs, 0.0)
        top, n = Counter(signed).most_common(1)[0]
        share = n / len(docs)
        if share >= AGREE:
            return Verdict("answered", NAMES[top], votes, docs, share)
        return Verdict("answered", "mixed", votes, docs, share)
