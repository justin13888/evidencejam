"""`sentence`, plus: an edge that names no direction is an unsigned vote, not a signed one (#76).

`sentence` rule 4 signs every `associated_with` / `correlated_with` edge through the node
polarities. On the dev gold, 66 of 240 associational edge effects are unsigned, and the sign the
polarities give is wrong for them: the edge says two things go together, or that one varies with
the other, without saying which way. Such an edge is read as unsigned (reason
"unsigned_association") when any of these hold:

1. Self-association: subject and object are the same variable once the direction words of their
   names are dropped ("Increased concentration of nitrate" with itself). The edge restates a trend
   in one variable, so it says nothing about a cause.
2. Unsigned outcome: the object names a variable with no direction (a variation, composition,
   assemblage, structure, difference, ordination, direction or shift) and its qualifier gives none
   either (not `increased` / `decreased`). "Shifted ectomycorrhizal fungal community composition".
3. Undirected sentence: the sentence reports that the outcome varied, differed, or was related
   ("Seeding method was associated with native cover", "A significant relationship was found")
   and holds no word that says which way.

An unsigned vote is included with no effect (effect None, included True): the edge bears on the
question, so the studies aggregator reads a question whose only evidence is unsigned as answered
`unclear` (D2), as the gold labels such items, and an unsigned vote never outvotes a signed one.
Excluding these votes instead turned such items into `no_evidence` (dev accuracy 0.622 against
0.637 included). Every other edge, `sentence` rule 3b's excluded "unsigned_difference" too, is read
exactly as `sentence` reads it.
"""

from __future__ import annotations

import re
from dataclasses import replace

from camoreasoning.components import Context
from camoreasoning.contracts import Candidates, EdgeVote
from camoreasoning.registry import register
from camoreasoning.strategies.interpreter import sentence
from camoreasoning.strategies.interpreter.sentence import ASSOCIATIONAL, SentenceInterpreter

DIRECTION_IN_NAME = re.compile(r"\b(?:increased|decreased|increases? in|declines? in|higher|lower|high|low)\b")
UNSIGNED_OUTCOME = re.compile(
    r"\b(?:variations?|compositions?|assemblages?|structures?|differen\w*|ordinations?|directions?|shift\w*)\b", re.I
)
SIGNED_QUALIFIERS = ("increased", "decreased")
UNDIRECTED = re.compile(
    r"\b(?:var(?:ied|y|ies)|differ(?:ed|s)?|different|important variables?|best model|axis|"
    r"relationships?|related (?:to|with)|(?:was|were) associated with|explained)\b",
    re.I,
)
DIRECTION_IN_SENTENCE = re.compile(
    r"\b(?:higher|highest|lower|lowest|more|most|less|least|fewer|greater|greatest|larger|smaller|best(?! model)|"
    r"positive\w*|negative\w*|increas\w*|decreas\w*|declin\w*|reduc\w*|rais\w*|poor\w*|improv\w*|gain\w*|loss|"
    r"absent|present|acidif\w*|closer|further)\b",
    re.I,
)


def _variable(node: dict) -> str:
    return " ".join(DIRECTION_IN_NAME.sub(" ", (node.get("name") or "").lower()).split())


def unsigned_association(edge: dict, subj: dict, obj: dict) -> bool:
    """The associational edge names no direction (rules 1-3 above)."""
    if edge.get("predicate") not in ASSOCIATIONAL:
        return False
    if _variable(subj) and _variable(subj) == _variable(obj):
        return True
    if UNSIGNED_OUTCOME.search(obj.get("name") or "") and obj.get("state_or_change_qualifier") not in SIGNED_QUALIFIERS:
        return True
    text = edge.get("original_sentence") or ""
    return bool(UNDIRECTED.search(text)) and not DIRECTION_IN_SENTENCE.search(text)


SIGNED_ASSOCIATION = ("associational", "reference_locus")  # `sentence` reasons for a signed association
UNSIGNED_VOTE = (None, True, "unsigned_association")  # (effect, included, reason)


def reads_unsigned(reason: str, edge: dict, subj: dict, obj: dict) -> bool:
    """`sentence` read this edge as a signed association, but the edge names no direction.

    The one test both `read_edge` and `UnsignedInterpreter.interpret` apply, so the two cannot drift.
    """
    return reason in SIGNED_ASSOCIATION and unsigned_association(edge, subj, obj)


def read_edge(
    edge: dict, obj: dict, cause_pol: int, outcome_pol: int, subj: dict | None = None
) -> tuple[int | None, bool, str]:
    """`sentence.read_edge`, with a signed association that names no direction read as unsigned."""
    effect, included, reason = sentence.read_edge(edge, obj, cause_pol, outcome_pol, subj)
    if reads_unsigned(reason, edge, subj or {}, obj):
        return UNSIGNED_VOTE
    return effect, included, reason


@register("interpreter", "unsigned")
class UnsignedInterpreter(SentenceInterpreter):
    def interpret(self, candidates: Candidates, ctx: Context) -> tuple[EdgeVote, ...]:
        g = ctx.graph
        effect, included, reason = UNSIGNED_VOTE

        def unsigned(v: EdgeVote) -> bool:
            e = g.edges[v.edge_id]
            return reads_unsigned(v.reason, e, g.nodes.get(e["subject"], {}), g.nodes.get(e["object"], {}))

        return tuple(
            replace(v, effect=effect, included=included, reason=reason) if unsigned(v) else v
            for v in super().interpret(candidates, ctx)
        )
