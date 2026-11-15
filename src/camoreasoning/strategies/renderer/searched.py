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

Wording (#113, #103): X and Y come from the question's spans only when `phrase` accepts them as a short
noun phrase (<= MAX_SPAN_WORDS words, no "?" or comma, not opening with a wh-word, auxiliary or bare verb,
not ending in a verb); otherwise the linked class label is used. A question with neither a cause nor an
outcome gives the one reason UNPARSED in both `answer` and `searched_for`.
"""

from __future__ import annotations

from collections import Counter

from camoreasoning.components import Context
from camoreasoning.contracts import Candidates, Certainty, Side, Verdict
from camoreasoning.registry import register
from camoreasoning.strategies.renderer.baseline import RosettaRenderer

MAX_IDS = 5
MAX_SPAN_WORDS = 6
UNPARSED = ("We couldn't find a cause and an outcome in this question. "
            'We answer questions like "What effect does X have on Y?"')  # fmt: skip
WH = {"what", "which", "how", "when", "where", "why", "who", "whom", "whose"}
AUX = {"do", "does", "did", "is", "are", "was", "were", "can", "could", "should", "will", "would", "may",
       "might", "must", "has", "have", "had"}  # fmt: skip
# Bare verbs that open a span ("remove buckthorn"): gerund where trivial, None means use the class label.
# Only words that are never nouns at the start of a span (not "plant", "seed", "burn", "harvest", "control").
GERUND = {"remove": "removing", "add": "adding", "apply": "applying", "install": "installing",
          "restore": "restoring", "reduce": "reducing", "introduce": "introducing", "reintroduce": "reintroducing",
          "eliminate": "eliminating", "protect": "protecting", "create": "creating", "replace": "replacing",
          "convert": "converting", "spray": "spraying", "fertilize": "fertilizing", "fertilise": "fertilising",
          "help": None, "make": None, "prevent": None, "improve": None, "affect": None, "allow": None,
          "kill": None, "stop": None, "get": None, "let": None, "keep": None}  # fmt: skip
# Verbs that cannot end a noun phrase ("tree seedlings survive").
END_VERBS = {"survive", "grow", "establish", "persist", "recover", "respond", "die", "thrive", "germinate",
             "reproduce", "colonize", "colonise", "spread", "regenerate", "return", "occur", "work", "help",
             "matter", "affect", "do", "does", "be", "is", "are"}  # fmt: skip
PREPOSITIONS = {"of", "to", "in", "on", "for", "with", "from", "by", "at", "into", "under", "after", "since"}
NOT_GERUND = {"during", "following", "including", "regarding", "concerning", "according", "being", "bring",
              "nothing", "something", "anything", "thing", "spring", "morning", "evening", "string"}  # fmt: skip


def side_label(side: Side, ctx: Context) -> str | None:
    """Label of the side's first linked class (else first linked node's name); None when unlinked."""
    tax = getattr(getattr(ctx, "taxonomy", None), "classes", None) or {}
    for r in side.classes:
        if r.id in tax:
            return tax[r.id].label
    nodes = getattr(getattr(ctx, "graph", None), "nodes", None) or {}
    for r in side.nodes:
        name = (nodes.get(r.id) or {}).get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _gerund_before(span: str, question: str) -> str | None:
    """The "-ing" word right before `span` in the question ("adding" in "Does adding woody debris ...")."""
    i = question.lower().find(span.lower())
    if i <= 0:
        return None
    words = question[:i].split()
    w = words[-1].lower() if words else ""
    return w if w.endswith("ing") and len(w) > 4 and w.isalpha() and w not in NOT_GERUND else None


def noun_phrase(span: str | None, question: str = "") -> str | None:
    """`span` as a short noun phrase, or None if it isn't one (#113)."""
    t = " ".join((span or "").split()).strip(" .")
    if not t:
        return None
    words = t.split()
    first = words[0].lower()
    if first in GERUND:
        if GERUND[first] is None:
            return None
        t = " ".join([GERUND[first], *words[1:]])
    elif not first.endswith("ing") and (g := _gerund_before(t, question)):
        t = f"{g} {t}"
    words = t.split()
    first, last = words[0].lower(), words[-1].lower()
    if len(words) > MAX_SPAN_WORDS or "?" in t or "," in t or first in WH or first in AUX or last in END_VERBS:
        return None
    return t


def phrase(side: Side, ctx: Context, question: str, default: str) -> tuple[str, bool]:
    """(X or Y for the sentence, whether it is a class/node label). The span if it is a short noun phrase,
    else the linked label, else `default`."""
    np = noun_phrase(side.text, question)
    if np:
        return np, False
    label = side_label(side, ctx)
    return (label, True) if label else (default, False)


def is_plural(x: str, label: bool = False) -> bool:
    """Plural subject for verb agreement: last word ends in 's' (not 'ss'/'us'/'is'); a class label with '&'
    names one category and stays singular. A gerund subject ("adding woody debris to streams") is singular;
    the head noun is the last word before the first preposition ("abundance of plants" is singular)."""
    words = x.lower().split()
    if not words or (label and "&" in x) or words[0].endswith("ing"):
        return False
    head = []
    for t in words:
        if t in PREPOSITIONS:
            break
        head.append(t)
    w = (head or words)[-1]
    return w.endswith("s") and not w.endswith(("ss", "us", "is")) and "&" not in x


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


def unparsed(f) -> bool:
    """Neither a cause nor an outcome was found in the question, so nothing was searched."""
    return f.cause.text is None and f.outcome.text is None and f.cause.empty and f.outcome.empty


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
        q = f.parsed.question.text or ""
        cause, cause_label = phrase(f.cause, ctx, q, "the intervention")
        outcome, _ = phrase(f.outcome, ctx, q, "the outcome")
        excluded = excluded_reasons(verdict)
        if unparsed(f):
            return UNPARSED, self.searched(verdict, candidates, ctx)
        if f.cause.empty or f.outcome.empty:
            why = []
            for name, s in (("cause", f.cause), ("outcome", f.outcome)):
                if not s.empty:
                    continue
                if not (s.text or "").strip():
                    why.append(f"we couldn't find a{'n' if name == 'outcome' else ''} {name} in the question")
                else:
                    np = noun_phrase(s.text, q)
                    what = f"the {name} '{np}'" if np else f"the question's {name}"
                    why.append(f"{what} matched no class or node in the graph")
            text = f"No claim was found because {' and '.join(why)}."
        elif excluded:
            n = sum(excluded.values())
            text = (f"The graph has {_plural(n, 'claim')} linking {cause} to {outcome}, but none gives a direction "
                    f"of effect.")  # fmt: skip
        else:
            verb = "affect" if is_plural(cause, cause_label) else "affects"
            text = f"The graph has no claim that {cause} {verb} {outcome}."
        if candidates.reversed:
            n = len(candidates.reversed)
            text += f" {_plural(n, 'claim')} {'runs' if n == 1 else 'run'} the other way, from {outcome} to {cause}."
        return text, self.searched(verdict, candidates, ctx)

    @staticmethod
    def searched(verdict: Verdict, c: Candidates, ctx: Context) -> str:
        f = c.frame
        if unparsed(f):
            return f"No edge search was run. {UNPARSED}"
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
