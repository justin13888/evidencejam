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
3b. `unchanged` outcome on a non-null edge whose strength reports a significant test (p <= 0.05,
   "significant"): no vote, reason "unsigned_difference". The schema reserves `unchanged` for a stable
   state, so a significant result there is an unsigned variable ("Microbial community structure",
   "Seeding method was associated with richness", F = 112, P = 0.000) that differed in an unstated
   direction. Reading it as a null turned a p = 1e-6 association into "no detectable association"
   (review_20 R08/R18). Negative predicates keep rule 5 ("prevented_change").
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
8. Reference locus (applies to the effect from rules 4 and 7): the sentence names only the undisturbed
   reference as the place of an extreme ("grasses were least evenly distributed in reference
   forests"), and the object qualifier copies that extreme onto the intervention (clearcut ->
   [decreased] evenness). The intervention is the other side of the comparison, so the effect is
   flipped and the reason becomes "reference_locus". All of these must hold: a `reference_undisturbed`
   comparator whose description is the sentence's only locative phrase; a management-intervention
   subject the sentence does not name; no two-arm wording (than, compared, versus, whereas, similar);
   degree words of one sign only, equal to the object qualifier's sign. 1 edge in the graph qualifies
   (review_20 R07); 11 looser variants were checked and are correct as annotated or name the subject.

Reversed edges always get one non-included vote, reason "reversed".
"""

from __future__ import annotations

import re
from typing import Literal

from camoreasoning.components import Context, EdgeInterpreter
from camoreasoning.contracts import Candidates, EdgeVote
from camoreasoning.registry import register
from camoreasoning.signs import is_null_finding, predicate_sign

ASSOCIATIONAL = ("associated_with", "correlated_with")
NEGATIVE_PREDICATES = ("prevents", "disrupts")
RESTATING = ("decreased", "absent")  # object qualifiers that restate a negative predicate's drop
DOUBLE_NEGATION: Literal["sentence", "schema"] = "sentence"

ALPHA = 0.05
P_VALUE = re.compile(r"\bp\s*(?:<=|<|≤|=)\s*(\d*\.?\d+)", re.I)
SCIENTIFIC = re.compile(r"10\s*\^?\s*\{?\s*[-−]\s*\d")
SIGNIFICANT = re.compile(r"\bsignifican(?:t|tly|ce)\b", re.I)
NOT_SIGNIFICANT = re.compile(r"\b(?:not|no|non-?|in)\s*significan|\bn\.?s\.?\b", re.I)

LOWER = r"least|lowest|fewest|smallest|lower|less|fewer"
HIGHER = r"most|highest|greatest|largest|higher|more"
TWO_ARM = re.compile(r"\bthan\b|compar|relative to|versus|\bvs\b|whereas|\bwhile\b|\bbetween\b|similar")
LOCATIVE = re.compile(r"\b(?:in|at|on|within|among) (?:the )?\w")
QUALIFIER_SIGN = {"increased": 1, "decreased": -1}


def reports_significance(edge: dict) -> bool:
    """The edge's strength reports a significant test: a p-value <= ALPHA, a 10^-k p-value, or the word."""
    raw = (edge.get("strength") or {}).get("quantitative_value")
    text = raw if isinstance(raw, str) else ""
    if not text or NOT_SIGNIFICANT.search(text):
        return False
    if any(float(p) <= ALPHA for p in P_VALUE.findall(text)) or SCIENTIFIC.search(text):
        return True
    return bool(SIGNIFICANT.search(text))


def reference_locus(edge: dict, subj: dict, obj: dict) -> bool:
    """Rule 8: the object qualifier copies the undisturbed reference's extreme onto the intervention."""
    q = QUALIFIER_SIGN.get(obj.get("state_or_change_qualifier") or "")
    sentence = " ".join((edge.get("original_sentence") or "").lower().split())
    term = (subj.get("entity_term") or subj.get("name") or "").lower()
    if q is None or subj.get("entity_type") != "management_intervention" or not term or term in sentence:
        return False
    if TWO_ARM.search(sentence) or len(LOCATIVE.findall(sentence)) != 1:
        return False
    raw = edge.get("comparator") or []
    refs = [c.get("comparator_description") or "" for c in (raw if isinstance(raw, list) else [raw])
            if isinstance(c, dict) and c.get("comparator_type") == "reference_undisturbed"]  # fmt: skip
    if not any(d and re.search(rf"\b(?:in|at|on|within|among) (?:the )?{re.escape(d.lower())}\b", sentence)
               for d in refs):  # fmt: skip
        return False
    lower, higher = re.search(rf"\b(?:{LOWER})\b", sentence), re.search(rf"\b(?:{HIGHER})\b", sentence)
    if bool(lower) == bool(higher):
        return False
    return (-1 if lower else 1) == q


def read_edge(
    edge: dict, obj: dict, cause_pol: int, outcome_pol: int, subj: dict | None = None
) -> tuple[int | None, bool, str]:
    """(effect, included, reason) for one forward edge. Pure, so tests can pin each rule."""
    if is_null_finding(edge):
        return 0, True, "null"
    if cause_pol == 0:
        return None, False, "unchanged_cause"
    predicate = edge.get("predicate")
    qualifier = obj.get("state_or_change_qualifier")
    pred = predicate_sign(predicate)
    if pred is None and predicate not in ASSOCIATIONAL:
        return None, False, "non_directional_predicate"
    if qualifier == "unchanged" and predicate not in NEGATIVE_PREDICATES and reports_significance(edge):
        return None, False, "unsigned_difference"
    flip = subj is not None and reference_locus(edge, subj, obj)
    if pred is None:
        effect = 0 if outcome_pol == 0 else cause_pol * outcome_pol
        return (-effect, True, "reference_locus") if flip and effect else (effect, True, "associational")
    if predicate in NEGATIVE_PREDICATES:
        if qualifier == "unchanged" or outcome_pol == 0:
            return None, False, "prevented_change"
        if DOUBLE_NEGATION == "sentence" and qualifier in RESTATING:
            return -(cause_pol * pred * outcome_pol), True, "double_negation"
    if outcome_pol == 0:
        return 0, True, "unchanged_outcome"
    effect = cause_pol * pred * outcome_pol
    return (-effect, True, "reference_locus") if flip else (effect, True, "signed")


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
                g.nodes.get(e["subject"], {}),
            )  # fmt: skip
            votes.append(EdgeVote(eid, e.get("source_document", ""), effect, included, reason,
                                  e.get("certainty_grade"), e.get("causal_language")))  # fmt: skip
        for eid in candidates.reversed:
            e = g.edges[eid]
            votes.append(EdgeVote(eid, e.get("source_document", ""), None, False, "reversed",
                                  e.get("certainty_grade"), e.get("causal_language")))  # fmt: skip
        return tuple(votes)
