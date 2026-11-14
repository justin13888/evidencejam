"""One vote per study, then the D2 rubric (ROADMAP item 6, decisions D2/D3).

1. Within a document, the majority effect over its included signed-or-null votes is the study's vote.
   A tie is an internally mixed study (vote None). Twins from one sentence usually split one claim by
   site, year or species, so a tie inside one study is heterogeneity, not a between-study conflict.
2. A direction (increase, decrease, no_effect) wins if at least 2/3 of studies give it; otherwise
   `mixed`. Internally mixed studies count in the denominator.
3. `unclear` only when no included vote carries any effect at all. Unlike `baseline`, studies that
   carry signed votes but are all internally tied give `mixed`: there is evidence, and it disagrees.
4. `no_evidence` iff no vote is included (D3: only reversed, non-directional or unchanged-cause edges).

`notes` carries machine tags for later stages, never parsed for the verdict itself:
"all_associational" (every included vote is associational, D1), "double_negation" (a vote used the
prevents/disrupts flip), "reference_comparator" (an included edge compares with undisturbed sites), and
"excluded:<reason>=<n>" per non-included reason.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from camoreasoning.components import Aggregator, Context
from camoreasoning.contracts import Candidates, EdgeVote, Verdict
from camoreasoning.registry import register

AGREE = 2 / 3  # decision D2
NAMES = {1: "increase", -1: "decrease", 0: "no_effect"}
ASSOCIATIONAL = ("associated_with", "correlated_with")


def study_vote(effects: list[int]) -> int | None:
    """Majority effect within one study; None on a tie."""
    top = Counter(effects).most_common(2)
    return None if len(top) > 1 and top[0][1] == top[1][1] else top[0][0]


def comparators(edges: dict, edge_id: str) -> list[dict]:
    raw = edges.get(edge_id, {}).get("comparator") or []
    return [c for c in (raw if isinstance(raw, list) else [raw]) if isinstance(c, dict)]


def notes_of(votes: tuple[EdgeVote, ...], ctx: Context) -> tuple[str, ...]:
    included = [v for v in votes if v.included]
    edges = ctx.graph.edges
    out = []
    if included and all(
        v.reason == "associational" or edges.get(v.edge_id, {}).get("predicate") in ASSOCIATIONAL for v in included
    ):
        out.append("all_associational")
    if any(v.reason == "double_negation" for v in included):
        out.append("double_negation")
    kinds = {c.get("comparator_type") for v in included for c in comparators(edges, v.edge_id)}
    if "reference_undisturbed" in kinds:
        out.append("reference_comparator")
    excluded = Counter(v.reason for v in votes if not v.included)
    out += [f"excluded:{r}={n}" for r, n in sorted(excluded.items())]
    return tuple(out)


@register("aggregator", "studies")
class StudyVote(Aggregator):
    def aggregate(self, votes: tuple[EdgeVote, ...], candidates: Candidates, ctx: Context) -> Verdict:
        notes = notes_of(votes, ctx)
        if not any(v.included for v in votes):
            return Verdict("no_evidence", None, votes, notes=notes)
        by_doc: dict[str, list[int]] = defaultdict(list)
        for v in votes:
            if v.included and v.effect is not None:
                by_doc[v.doc_id].append(v.effect)
        docs = tuple((d, study_vote(es)) for d, es in sorted(by_doc.items()))
        if not docs:
            return Verdict("answered", "unclear", votes, docs, 0.0, notes)
        signed = [e for _, e in docs if e is not None]
        if not signed:
            return Verdict("answered", "mixed", votes, docs, 0.0, notes)
        top, n = Counter(signed).most_common(1)[0]
        share = n / len(docs)
        direction = NAMES[top] if share >= AGREE else "mixed"
        return Verdict("answered", direction, votes, docs, share, notes)
