"""Variable-level sign per edge, with question-relative polarities from the retriever."""

from __future__ import annotations

from camoreasoning.components import Context, EdgeInterpreter
from camoreasoning.contracts import Candidates, EdgeVote
from camoreasoning.registry import register
from camoreasoning.signs import is_null_finding, predicate_sign

UNSIGNED_AS_POSITIVE = ("associated_with", "correlated_with")  # qualifiers then carry the direction


@register("interpreter", "baseline")
class SignInterpreter(EdgeInterpreter):
    def interpret(self, candidates: Candidates, ctx: Context) -> tuple[EdgeVote, ...]:
        g = ctx.graph
        votes = []
        for eid in candidates.forward:
            e = g.edges[eid]
            kw = dict(edge_id=eid, doc_id=e.get("source_document", ""), certainty_grade=e.get("certainty_grade"),
                      causal_language=e.get("causal_language"))  # fmt: skip
            if is_null_finding(e):
                votes.append(EdgeVote(effect=0, included=True, reason="null", **kw))
                continue
            pred = predicate_sign(e.get("predicate"))
            reason = "signed"
            if pred is None and e.get("predicate") in UNSIGNED_AS_POSITIVE:
                pred, reason = 1, "unsigned_predicate"
            if pred is None:
                votes.append(EdgeVote(effect=None, included=False, reason="non_directional_predicate", **kw))
                continue
            sp, op = candidates.cause_nodes[e["subject"]], candidates.outcome_nodes[e["object"]]
            if sp == 0:
                votes.append(EdgeVote(effect=None, included=False, reason="unchanged_cause", **kw))
            elif op == 0:
                votes.append(EdgeVote(effect=0, included=True, reason="unchanged_outcome", **kw))
            else:
                votes.append(EdgeVote(effect=sp * pred * op, included=True, reason=reason, **kw))
        for eid in candidates.reversed:
            e = g.edges[eid]
            votes.append(EdgeVote(eid, e.get("source_document", ""), None, False, "reversed",
                                  e.get("certainty_grade"), e.get("causal_language")))  # fmt: skip
        return tuple(votes)
