"""Executable done-check for item 15 (issue #15): every answered text agrees with the verdict it renders.

Replaces the 20-answer human review as the bar (experiments/renderer/review_20.md stays as the audited
baseline). Three checks, each reading the text against the fields it claims to render:

- d1: when every included vote is associational (`grader.rubric.is_associational`), the text (with the
  question's own cause and outcome spans removed) uses no causal wording, says "associational evidence
  only", and a directional verdict says "associated with".
- votes: "Across N studies" has N == len(verdict.doc_effects), and each breakdown group's count equals the
  number of studies with that effect (one vote per study; an internally tied study is "mixed results
  within the study"). No "Across" when there are no study votes.
- direction: the verdict sentence states `verdict.direction` and no other direction, and that direction
  follows from the study votes under D2 (a direction needs at least 2/3 of studies, else mixed; no study
  vote at all is unclear; votes that are all internally tied are mixed).

0 LLM calls. `violations` is pure; experiments/renderer/consistency_check.py runs it over every answered
result and tests/strategies/test_renderer_faithful.py runs it over every class pair.
"""

from __future__ import annotations

import re
from collections import Counter

from camoreasoning.contracts import Verdict
from camoreasoning.strategies.aggregator.studies import AGREE, NAMES

CAUSAL = re.compile(
    r"\b(causes?|caused|causing|increases?|increased|decreases?|decreased|leads? to|reduces?|reduced|raises?|"
    r"raised|improves?|improved|effects?|affects?|drives?)\b",
    re.I,
)
ACROSS = re.compile(r"Across (\d+) stud(?:y|ies): ")
GROUP_EFFECT = {
    "an increase": 1,
    "a positive association": 1,
    "a decrease": -1,
    "a negative association": -1,
    "no detectable effect": 0,
    "no detectable association": 0,
    "mixed results within the study": None,
}
GROUP = re.compile(r"(?:^|, | and )(\d+) (?:reports? )?(" + "|".join(map(re.escape, GROUP_EFFECT)) + r") \(")
STATES = {
    "increase": re.compile(r"\bincreases?\b|\ban increase\b|associated with higher|a positive association"),
    "decrease": re.compile(r"\bdecreases?\b|\ba decrease\b|associated with lower|a negative association"),
    "no_effect": re.compile(r"no detectable (?:effect|association)"),
    "mixed": re.compile(r"\bdisagree\b|mixed results|\bare mixed\b"),
    "unclear": re.compile(r"\bunclear\b|no direction can be read"),
}

CHANGE = re.compile(r"\bchanges?\b|associated with a change in|points to a change in")


def expected_direction(doc_effects: tuple) -> str:
    """D2 (aggregator `studies`): the direction the study votes support."""
    if not doc_effects:
        return "unclear"
    signed = [e for _, e in doc_effects if e is not None]
    if not signed:
        return "mixed"
    top, n = Counter(signed).most_common(1)[0]
    return NAMES[top] if n / len(doc_effects) >= AGREE else "mixed"


def _strip(text: str, spans: tuple[str, ...]) -> str:
    for s in sorted({s for s in spans if s}, key=len, reverse=True):
        text = text.replace(s, " ").replace(s[:1].upper() + s[1:], " ")
    return text


def violations(text: str, verdict: Verdict, associational: bool, spans: tuple[str, ...] = ()) -> list[str]:
    """Every way `text` disagrees with `verdict`; [] when consistent. `spans` are the question's cause and
    outcome text, which are the asker's words and are not checked for causal wording."""
    out: list[str] = []
    bare = _strip(text, spans)
    head = bare.split(" Across ")[0]
    direction = verdict.direction or "unclear"
    if associational:
        if m := CAUSAL.search(bare):
            out.append(f"d1: causal wording {m.group(0)!r} on all-associational evidence")
        if "associational evidence only" not in text:
            out.append("d1: all-associational answer does not say 'associational evidence only'")
        if direction in ("increase", "decrease") and "associated with" not in head:
            out.append("d1: directional all-associational answer does not say 'associated with'")
    n_docs = len(verdict.doc_effects)
    across = ACROSS.findall(text)
    if n_docs and across != [str(n_docs)]:
        out.append(f"votes: 'Across' states {across} studies, verdict counts {n_docs}")
    if not n_docs and across:
        out.append(f"votes: 'Across' states {across} studies, verdict has no study votes")
    if n_docs and across:
        body = text.split(ACROSS.search(text).group(0), 1)[1]
        stated: Counter = Counter()
        for n, phrase in GROUP.findall(body):
            stated[GROUP_EFFECT[phrase]] += int(n)
        actual = Counter(e if e in (1, -1, 0) else None for _, e in verdict.doc_effects)
        if stated != actual:
            out.append(f"votes: breakdown {dict(stated)} != study votes {dict(actual)}")
    said = {d for d, rx in STATES.items() if rx.search(head)}
    if not said and direction in ("increase", "decrease") and CHANGE.search(head):
        said = {direction}  # an outcome with no natural direction (composition) states its sign as "a change"
    if direction not in said:
        out.append(f"direction: verdict sentence does not state {direction!r}")
    if said - {direction}:
        out.append(f"direction: verdict sentence also states {sorted(said - {direction})}")
    if (want := expected_direction(verdict.doc_effects)) != direction:
        out.append(f"direction: study votes give {want!r} under D2, verdict says {direction!r}")
    return out
