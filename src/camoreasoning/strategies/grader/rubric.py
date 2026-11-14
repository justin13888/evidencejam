"""D4 rubric grader: median edge grade, one level lower for mixed or purely associational evidence.

Rule (ROADMAP D4):
1. None iff ``verdict.status == "no_evidence"``.
2. Take the lower median of ``certainty_grade`` over the included votes (as baseline). If no
   included vote carries a valid grade, return ``"low"`` (as baseline).
3. Drop one level (moderate -> low -> very_low, floor very_low) if ``verdict.direction == "mixed"``
   OR every included vote is associational.
4. Never return ``high``: cap the result at ``moderate`` (the graph has no ``high`` grades).

A vote is associational when its graph edge's ``predicate`` is ``associated_with`` or
``correlated_with`` (read from ``ctx.graph``, so it works with any interpreter), or when the
interpreter tagged it with reason ``"associational"``. Null votes on negated ``causes`` edges are
therefore not associational.

``OBSERVATIONAL_SINGLE_STUDY_DROP`` (default off, for the gold comparison): when True, the drop also
triggers when all included votes come from exactly one document and every study design on those
edges is observational. The design lives in ``evidential_basis.evidence_types`` on each edge (the
schema's ``study_design`` slot is not populated in causal_graph.json). The total drop is at most one
level whichever conditions hold. 0 LLM calls, deterministic.
"""

from __future__ import annotations

from camoreasoning.components import Context, Grader
from camoreasoning.contracts import Certainty, EdgeVote, Verdict
from camoreasoning.registry import register
from camoreasoning.schema import CERTAINTY_ORDER

OBSERVATIONAL_SINGLE_STUDY_DROP = False

ASSOCIATIONAL_PREDICATES = frozenset({"associated_with", "correlated_with"})
OBSERVATIONAL_DESIGNS = frozenset({"observational_cross_sectional", "observational_longitudinal"})
_LEVELS = sorted(CERTAINTY_ORDER, key=CERTAINTY_ORDER.__getitem__)
CAP = "moderate"


def _edge(v: EdgeVote, ctx: Context) -> dict:
    return ctx.graph.edges.get(v.edge_id) or {}


def is_associational(v: EdgeVote, ctx: Context) -> bool:
    return v.reason == "associational" or _edge(v, ctx).get("predicate") in ASSOCIATIONAL_PREDICATES


def _single_observational_study(votes: tuple[EdgeVote, ...], ctx: Context) -> bool:
    docs = {v.doc_id or _edge(v, ctx).get("source_document", "") for v in votes}
    if len(docs) != 1:
        return False
    designs = {t for v in votes for t in (_edge(v, ctx).get("evidential_basis") or {}).get("evidence_types") or ()}
    return bool(designs) and designs <= OBSERVATIONAL_DESIGNS


@register("grader", "rubric")
class RubricGrade(Grader):
    def grade(self, verdict: Verdict, ctx: Context) -> Certainty | None:
        if verdict.status == "no_evidence":
            return None
        included = verdict.included
        grades = sorted(
            (v.certainty_grade for v in included if v.certainty_grade in CERTAINTY_ORDER),
            key=CERTAINTY_ORDER.__getitem__,
        )
        if not grades:
            return "low"
        level = CERTAINTY_ORDER[grades[(len(grades) - 1) // 2]]
        drop = verdict.direction == "mixed" or all(is_associational(v, ctx) for v in included)
        if OBSERVATIONAL_SINGLE_STUDY_DROP and not drop:
            drop = _single_observational_study(included, ctx)
        return _LEVELS[min(max(level - drop, 0), CERTAINTY_ORDER[CAP])]
