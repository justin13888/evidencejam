"""`baseline` wording for answered questions; a specific no_evidence answer and `searched_for` (item 8).

CHALLENGE: `searched_for` is "what you looked for and didn't find: which nodes, attributes or
relations", e.g. "edges whose subject node is mowing or cutting and whose object node's
measured_attribute is soil carbon or organic matter". This renderer names, per side:
- the classes searched (label and id) and how many graph nodes they cover,
- for the outcome, the most common free-text `measured_attribute` values of those nodes,
- the relation searched (cause -> outcome, any directional predicate),
and then what was found instead: forward edges that exist but cannot vote, counted by reason (D3:
moderators/mediators, categorical causes, "prevented a change"), and edges running the other way,
named by id (at most MAX_IDS). The no_evidence answer text says which of those cases applies.
Answered text is untouched (item 15 owns it). 0 LLM calls.
"""

from __future__ import annotations

from collections import Counter

from camoreasoning.components import Context
from camoreasoning.contracts import Candidates, Certainty, Side, Verdict
from camoreasoning.registry import register
from camoreasoning.strategies.renderer.baseline import RosettaRenderer

MAX_IDS = 5
MAX_ATTRS = 3
WHY = {
    "non_directional_predicate": "moderate, mediate or regulate it without a direction",
    "unchanged_cause": "compare categories of the cause, with no direction",
    "prevented_change": "say it prevented a change rather than giving a direction",
    "unsigned_difference": "report a significant difference without saying which way",
    "unsigned": "carry no usable sign",
}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _side(side: Side, nodes: dict[str, int], ctx: Context) -> str:
    names = [f"{ctx.taxonomy.classes[r.id].label} ({r.id})" for r in side.classes if r.id in ctx.taxonomy.classes]
    names += [f"{ctx.graph.nodes[r.id].get('name', r.id)} ({r.id})" for r in side.nodes if r.id in ctx.graph.nodes]
    if names:
        return f"{' or '.join(names)}, {_plural(len(nodes), 'graph node')}"
    if side.text:
        return f"'{side.text}', which matched no class or node"
    return "not named in a form we could parse"


def _attributes(nodes: dict[str, int], ctx: Context) -> list[str]:
    c = Counter(
        a for n in nodes
        if isinstance(a := ctx.graph.nodes.get(n, {}).get("measured_attribute"), str) and ":" not in a
    )  # fmt: skip
    return [a for a, _ in c.most_common(MAX_ATTRS)]


def excluded_reasons(verdict: Verdict) -> Counter:
    return Counter(v.reason for v in verdict.votes if not v.included and v.reason != "reversed")


@register("renderer", "searched")
class SearchedRenderer(RosettaRenderer):
    def render(
        self, verdict: Verdict, candidates: Candidates, certainty: Certainty | None, ctx: Context
    ) -> tuple[str, str | None]:
        if verdict.status != "no_evidence":
            return super().render(verdict, candidates, certainty, ctx)
        f = candidates.frame
        cause, outcome = f.cause.text or "the intervention", f.outcome.text or "the outcome"
        excluded = excluded_reasons(verdict)
        if f.cause.empty or f.outcome.empty:
            missing = " or ".join(n for n, s in (("cause", f.cause), ("outcome", f.outcome)) if s.empty)
            text = f"We could not match the question's {missing} to anything in the graph, so no claim was found."
        elif excluded:
            n = sum(excluded.values())
            text = (f"The graph has {_plural(n, 'claim')} linking {cause} to {outcome}, but none gives a direction "
                    f"of effect.")  # fmt: skip
        else:
            text = f"The graph has no claim that {cause} affects {outcome}."
        if candidates.reversed:
            n = len(candidates.reversed)
            text += f" {_plural(n, 'claim')} {'runs' if n == 1 else 'run'} the other way, from {outcome} to {cause}."
        return text, self.searched(verdict, candidates, ctx)

    @staticmethod
    def searched(verdict: Verdict, c: Candidates, ctx: Context) -> str:
        f = c.frame
        if f.cause.text is None and f.outcome.text is None and f.cause.empty and f.outcome.empty:
            return ("no edge search was run: the question did not name a cause and an outcome in a form we could "
                    "parse (\"What effect does X have on Y?\").")  # fmt: skip
        out = f"edges whose subject is {_side(f.cause, c.cause_nodes, ctx)}"
        out += f", and whose object is {_side(f.outcome, c.outcome_nodes, ctx)}"
        attrs = _attributes(c.outcome_nodes, ctx)
        if attrs:
            out += f" (measured_attribute {', '.join(attrs)})"
        out += "; relation: any directional predicate from cause to outcome."
        excluded = excluded_reasons(verdict)
        found = [f"{n} {WHY.get(r, 'carry no usable sign')}" for r, n in excluded.most_common()]
        out += f" Found {_plural(len(c.forward), 'forward edge')}"
        out += f", none usable ({'; '.join(found)})." if found else "."
        if c.reversed:
            ids = ", ".join(c.reversed[:MAX_IDS]) + (", ..." if len(c.reversed) > MAX_IDS else "")
            n = len(c.reversed)
            out += f" {_plural(n, 'edge')} {'runs' if n == 1 else 'run'} the reverse way, outcome to cause: {ids}."
        return out
