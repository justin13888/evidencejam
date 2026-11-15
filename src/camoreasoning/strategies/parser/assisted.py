"""`freeform` plus one LLM call for questions it cannot split (issue #114). For `ask` only.

The judged batch run keeps `freeform` (0 calls); `ask.sh` selects this parser. Order:
1. `freeform`. If it yields both a cause and an outcome, that result stands (0 calls; template questions
   are therefore parsed exactly as in baseline).
2. A 0-call "how do I control / reduce / get rid of / manage X" rule: outcome = "X abundance", no cause
   (an open-cause question; `ask` then lists the causes with evidence on that outcome).
3. Otherwise, if an LLM is configured, ONE `ctx.llm.chat_json` call extracts the cause (intervention or
   condition) and the outcome as short noun phrases, strict JSON {"cause": str|null, "outcome": str|null}.
   Each phrase is cleaned like a freeform span; anything malformed is ignored. Any LLMError, a missing
   endpoint, or an unusable reply keeps the `freeform` result, so `ask` refuses as before.

The QuestionParser contract says 0 calls; this strategy breaks that on purpose, only on the ask path, as
issue #114 approved. Never raises.
"""

from __future__ import annotations

import re
from collections import defaultdict

from camoreasoning.components import Context, QuestionParser
from camoreasoning.contracts import Frame, ParsedQuestion, Question
from camoreasoning.llm import LLMError
from camoreasoning.registry import register
from camoreasoning.strategies.parser.freeform import FreeformParser, clean_span, normalise

MAX_QUESTION_CHARS = 600  # sent to the model; longer questions are truncated
MAX_PHRASE_CHARS = 80
MAX_TOKENS = 80  # reply is ~20-30 tokens

CONTROL = re.compile(
    r"^(?:how (?:do|can|should|could|would) (?:i|we|you|one) |how to |what(?:'s| is) the best way to |"
    r"best way to |what (?:works|helps) (?:best )?(?:to|for) )(?:best )?"
    r"(?:control|controlling|reduce|reducing|manage|managing|get rid of|getting rid of|eliminate|eliminating|"
    r"remove|removing|eradicate|eradicating|kill|killing|suppress|suppressing|stop|stopping)"
    r" (?P<x>.+)$",
    re.I,
)

WHERE = re.compile(r"\s+(?:in|on|at|from|around|along|near|within|across|throughout|this|next|every)\s.*$", re.I)

SYSTEM = (
    "You read one ecology or ecological-restoration question and extract two short noun phrases: "
    "the cause (the intervention, management action or condition, e.g. 'prescribed burning', 'mulch', "
    "'herbicide application', 'grazing') and the outcome (what is measured, e.g. 'dogwood abundance', "
    "'native plant richness', 'soil moisture'). Use the question's own words, 1-6 words each, no clauses. "
    "For 'how do I control / reduce / get rid of / manage X' the outcome is 'X abundance' and the cause is "
    "null unless a method is named. If a side is not stated or implied, use null. "
    'Reply only JSON: {"cause": string_or_null, "outcome": string_or_null}'
)


def _phrase(value, cause: bool) -> str | None:
    if not isinstance(value, str) or len(value) > MAX_PHRASE_CHARS:
        return None
    return clean_span(normalise(value), cause)


def control_target(text: str) -> str | None:
    """ "How do I control garlic mustard?" -> "garlic mustard abundance"; None if not that shape."""
    m = CONTROL.match(normalise(text)[:MAX_QUESTION_CHARS])
    x = clean_span(WHERE.sub("", m["x"]), False) if m else None
    if not x:
        return None
    return x if re.search(r"\b(?:abundance|density|cover|biomass)$", x, re.I) else f"{x} abundance"


@register("parser", "assisted")
class AssistedParser(QuestionParser):
    def __init__(self):
        self._free = FreeformParser()

    def parse(self, question: Question, ctx: Context) -> ParsedQuestion:
        base = self._free.parse(question, ctx)
        if base.cause_text and base.outcome_text:
            return base
        text = question.text or ""
        if target := control_target(text):
            return ParsedQuestion(question, None, target, False)
        if not normalise(text) or not ctx.llm.available:
            return base
        try:
            reply = ctx.llm.chat_json(SYSTEM, normalise(text)[:MAX_QUESTION_CHARS], max_tokens=MAX_TOKENS,
                                      purpose="parser")  # fmt: skip
        except LLMError:
            return base
        if not isinstance(reply, dict):
            return base
        cause, outcome = _phrase(reply.get("cause"), True), _phrase(reply.get("outcome"), False)
        if not (cause or outcome):
            return base
        return ParsedQuestion(question, cause or base.cause_text, outcome or base.outcome_text, False)


def causes_with_evidence(frame: Frame, ctx: Context, n: int = 6) -> list[tuple[str, int]]:
    """Open-cause help for `ask`: cause class labels with the number of studies that have a claim on the
    frame's outcome (its linked classes' nodes and linked nodes), most studied first. 0 calls."""
    tax = ctx.taxonomy
    targets = {r.id for r in frame.outcome.nodes}
    for r in frame.outcome.classes:
        targets |= {lb.node_id for lb in tax.nodes_of(r.id)}
    docs: dict[str, set] = defaultdict(set)
    for e in ctx.graph.edges.values():
        if e.get("object") in targets:
            for lb in tax.classes_of(e.get("subject")):
                c = tax.classes.get(lb.class_id)
                if c is not None and c.kind in ("cause", "both"):
                    docs[c.label].add(e.get("source_document", ""))
    ranked = sorted(((label, len(d)) for label, d in docs.items()), key=lambda x: (-x[1], x[0]))
    return ranked[:n]
