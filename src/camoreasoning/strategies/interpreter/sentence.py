"""Edge -> vote, read the way the source sentence reads (ROADMAP item 6; decisions D1-D3).

Same sign algebra as `baseline` (question-relative node polarities x predicate sign; the node labels
already fold in each node's qualifier), plus the rules the graph profile showed are needed. Evidence
for each rule is in experiments/profile/README.md and, for double negation, in
tests/strategies/test_direction.py, which pins every `prevents`/`disrupts` edge to its sentence.

Rules, in order:
1. Null finding (`signs.is_null_finding`): effect 0, reason "null". Null is no_effect, never decrease.
   Checked first: 130 of the 166 edges with an `unchanged` subject are nulls ("Soil moisture was not
   related to hatching success"), annotated with the subject as the unchanged side.
2. `unchanged` cause on a non-null edge (cause polarity 0): no vote (D3), reason "unchanged_cause".
   The other 36 are categorical contrasts (zone type, site status, PCA axes) with no usable sign.
3. Predicate with no sign (moderates, mediates, regulates, precedes, unknown): no vote,
   reason "non_directional_predicate" (D3).
4. `associated_with` / `correlated_with`: signed through the node polarities and tagged
   "associational" (D1). Downstream wording must stay associational.
5. Negative predicate (`prevents`, `disrupts`):
   - object `unchanged` ("prevented the increase in diversity", "prevented the water table drop"):
     these name a change that did not happen. They are neither a null nor a sign, so no vote
     (reason "prevented_change").
   - object qualifier in RESTATING ("decreased", "absent"): the qualifier restates the drop
     ("rewetting prevents decreased Kalmia cover" for "Kalmia cover was lower in rewetted
     trenches"). The negative predicate and the negative object are one negation, not two, so the
     schema product is flipped. Reason "double_negation". Of the 33 such edges, 30 have a sentence
     that settles the sign: the flip matches 29 of them, the schema product 1 (cone containers).
   - other negative objects ("terminated"): the schema product is kept (1 of 1 matches the sentence).
   `DOUBLE_NEGATION = "schema"` turns the flip off so gold can arbitrate between the readings.
6. `unchanged` outcome on any other predicate: effect 0, reason "unchanged_outcome". These are
   untagged nulls ("X associated with no change in Y").
7. Otherwise: effect = cause polarity x predicate sign x outcome polarity, reason "signed".

Reversed edges always get one non-included vote, reason "reversed".
"""

from __future__ import annotations

from typing import Literal

from camoreasoning.components import Context, EdgeInterpreter
from camoreasoning.contracts import Candidates, EdgeVote
from camoreasoning.registry import register
from camoreasoning.signs import is_null_finding, predicate_sign

ASSOCIATIONAL = ("associated_with", "correlated_with")
NEGATIVE_PREDICATES = ("prevents", "disrupts")
RESTATING = ("decreased", "absent")  # object qualifiers that restate a negative predicate's drop
DOUBLE_NEGATION: Literal["sentence", "schema"] = "sentence"


def read_edge(edge: dict, obj: dict, cause_pol: int, outcome_pol: int) -> tuple[int | None, bool, str]:
    """(effect, included, reason) for one forward edge. Pure, so tests can pin each rule."""
    if is_null_finding(edge):
        return 0, True, "null"
    if cause_pol == 0:
        return None, False, "unchanged_cause"
    predicate = edge.get("predicate")
    pred = predicate_sign(predicate)
    if pred is None and predicate in ASSOCIATIONAL:
        effect = 0 if outcome_pol == 0 else cause_pol * outcome_pol
        return effect, True, "associational"
    if pred is None:
        return None, False, "non_directional_predicate"
    qualifier = obj.get("state_or_change_qualifier")
    if predicate in NEGATIVE_PREDICATES:
        if qualifier == "unchanged" or outcome_pol == 0:
            return None, False, "prevented_change"
        if DOUBLE_NEGATION == "sentence" and qualifier in RESTATING:
            return -(cause_pol * pred * outcome_pol), True, "double_negation"
    if outcome_pol == 0:
        return 0, True, "unchanged_outcome"
    return cause_pol * pred * outcome_pol, True, "signed"


@register("interpreter", "sentence")
class SentenceInterpreter(EdgeInterpreter):
    def interpret(self, candidates: Candidates, ctx: Context) -> tuple[EdgeVote, ...]:
        g = ctx.graph
        votes = []
        for eid in candidates.forward:
            e = g.edges[eid]
            effect, included, reason = read_edge(
                e, g.nodes.get(e["object"], {}),
                candidates.cause_nodes.get(e["subject"], 1), candidates.outcome_nodes.get(e["object"], 1),
            )  # fmt: skip
            votes.append(EdgeVote(eid, e.get("source_document", ""), effect, included, reason,
                                  e.get("certainty_grade"), e.get("causal_language")))  # fmt: skip
        for eid in candidates.reversed:
            e = g.edges[eid]
            votes.append(EdgeVote(eid, e.get("source_document", ""), None, False, "reversed",
                                  e.get("certainty_grade"), e.get("causal_language")))  # fmt: skip
        return tuple(votes)
