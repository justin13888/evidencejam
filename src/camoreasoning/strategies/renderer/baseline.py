"""Rosetta-style sentence with a single hedge source (the answer's certainty), plus study counts."""

from __future__ import annotations

from collections import Counter

from camoreasoning.components import Context, Renderer
from camoreasoning.contracts import Candidates, Certainty, Verdict
from camoreasoning.registry import register
from camoreasoning.schema import CERTAINTY_MODIFIER, VERY_LOW_TEMPLATE

VERB = {
    "increase": "increases",
    "decrease": "decreases",
    "no_effect": "has no detectable effect on",
    "mixed": "has mixed effects on",
    "unclear": "has an unclear effect on",
}
BASE_VERB = {"increases": "increase", "decreases": "decrease", "has": "have"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def counts(verdict: Verdict) -> str:
    c = Counter(e for _, e in verdict.doc_effects)
    parts = [f"{c[1]} report an increase" if c[1] else "", f"{c[-1]} a decrease" if c[-1] else "",
             f"{c[0]} no effect" if c[0] else "", f"{c[None]} are internally mixed" if c[None] else ""]  # fmt: skip
    n_docs = len(verdict.doc_effects)
    studies = f"{n_docs} {'study' if n_docs == 1 else 'studies'}"
    return f"Across {studies}: " + ", ".join(p for p in parts if p) + "." if n_docs else ""


@register("renderer", "baseline")
class RosettaRenderer(Renderer):
    def render(
        self, verdict: Verdict, candidates: Candidates, certainty: Certainty | None, ctx: Context
    ) -> tuple[str, str | None]:
        f = candidates.frame
        cause, outcome = f.cause.text or "the intervention", f.outcome.text or "the outcome"
        if verdict.status == "no_evidence":
            text = f"The graph has no claim linking {cause} to {outcome}."
            if candidates.reversed:
                text += f" ({_plural(len(candidates.reversed), 'claim')} run the other way, from {outcome} to {cause}.)"
            return text, self.searched_for(candidates, ctx)
        verb = VERB[verdict.direction or "unclear"]
        if certainty == "very_low":
            head = VERY_LOW_TEMPLATE.format(subject=cause, object=outcome) + f" (direction: {verdict.direction})."
        else:
            mod = CERTAINTY_MODIFIER.get(certainty or "", "")
            if mod:
                first, _, rest = verb.partition(" ")
                verb = f"{mod} {BASE_VERB.get(first, first)} {rest}".strip() if mod == "may" else f"{mod} {verb}"
            head = f"{cause[:1].upper()}{cause[1:]} {verb} {outcome}."
        return f"{head} {counts(verdict)}".strip(), None

    @staticmethod
    def searched_for(c: Candidates, ctx: Context) -> str:
        def side(name: str, s, nodes: dict) -> str:
            labels = [ctx.taxonomy.classes[r.id].label for r in s.classes if r.id in ctx.taxonomy.classes]
            what = f"classes {labels}" if labels else f"{len(nodes)} nodes matching '{s.text}'"
            if s.text is None:
                return f"{name} (the question did not name one we could parse)"
            return f"{name} in {what}" if nodes or labels else f"{name} matching '{s.text}' (no node matched)"

        f = c.frame
        return (f"edges whose {side('subject', f.cause, c.cause_nodes)} and whose "
                f"{side('object', f.outcome, c.outcome_nodes)}; 0 found"
                + (f", {len(c.reversed)} in the reverse direction" if c.reversed else ""))  # fmt: skip
