"""Faithful answered text (ROADMAP item 15); no_evidence text and `searched_for` from `searched` (item 8).

An answered text is one verdict sentence, then the vote breakdown by study:

    Prescribed burning probably increases native plant richness (moderate certainty). Across 4 studies:
    3 report an increase (Lee 2018; Ortiz 2020; Smith 2014) and 1 no detectable effect (Strack 2014).

Rules:
1. One hedge source, the answer's certainty (schema CertaintyGradeEnum). Every sentence that states a
   direction (increase, decrease, no_effect) takes its modifier: high none, moderate "probably", low
   "may"; very_low has no modifier and uses
   VERY_LOW_TEMPLATE ("The evidence is very uncertain about the effect of X on Y"), then says where the
   studies point. The certainty is also stated in words, "(low certainty)", exactly once. No other hedge
   words. The organizer's rendering guide maps very_low to "might"; the schema wins. "may ... (very low
   certainty)" is never used: "may" is the schema's low modifier, a weaker hedge than very_low.
2. D1: when every included vote is associational (`grader.rubric.is_associational`), no causal verb and
   no "effect": "X may be associated with higher Y (low certainty; associational evidence only)",
   very_low "The evidence is very uncertain about the association between X and Y, but it points to X
   being associated with higher Y (...)". The breakdown says "a positive/negative association" and
   "no detectable association". Partly associational evidence keeps causal verbs, as D1 decides.
3. no_effect is "X probably has no detectable effect on Y" (a null is a finding, not a decrease; review
   round 2 showed a bare "Studies found no detectable effect (moderate certainty)" reads as unhedged).
   mixed and unclear state no direction, so they take no modifier; the certainty in words is the hedge.
   mixed says "Studies disagree about ..." only when studies report different signs; otherwise "Results
   on ... are mixed" or "The one study on ... reports mixed results". unclear says "The direction of ...
   is unclear". None of these use increase/decrease/higher/lower in the verdict sentence.
4. The breakdown groups `verdict.doc_effects` (one vote per study) by effect, so the study count equals
   len(doc_effects); largest group first. Internally tied studies (effect None) are "mixed results within
   the study" (a tie may be an increase against a null, not a contradiction). Each group names at most
   MAX_NAMES studies as "Surname Year" (first author's text before the first comma; "n.d." without a
   year; else DOI; else doc id), then "+N more". Identical labels get a/b/... suffixes, only when two
   studies in the answer share one.
5. Wording (#113): X and Y pass `searched.phrase` (short noun phrase, else the class label). A plural X
   takes plural verbs. An outcome with no natural direction (UNDIRECTED classes, or Y naming composition,
   similarity or ordination) says "changes Y" / "associated with a change in Y", never "higher" or
   "increases". Surnames: all-caps title-cased ("McLACHLAN" -> "McLachlan"); a given name left before the
   comma ("Anne Naeth, M.") or a "Given Surname" string with no comma gives the last token.
6. 0 LLM calls, reads only existing CAMO fields (`authors`, `year`, `doi`), never raises: any failure
   falls back to the `searched`/`baseline` text.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict

from camoreasoning.components import Context
from camoreasoning.contracts import Candidates, Certainty, Verdict
from camoreasoning.registry import register
from camoreasoning.schema import CERTAINTY_MODIFIER, VERY_LOW_TEMPLATE
from camoreasoning.strategies.grader.rubric import is_associational
from camoreasoning.strategies.renderer.searched import SearchedRenderer, is_plural, phrase

MAX_NAMES = 3
ORDER = (1, -1, 0, None)
WITHIN = "mixed results within the study"
CAUSAL_GROUP = {1: "an increase", -1: "a decrease", 0: "no detectable effect", None: WITHIN}
ASSOC_GROUP = {1: "a positive association", -1: "a negative association", 0: "no detectable association", None: WITHIN}
VERB = {"increase": ("increases", "increase"), "decrease": ("decreases", "decrease")}  # 3rd person, base
SIGN = {"increase": 1, "decrease": -1, "no_effect": 0}
# Outcome classes (taxonomy/classes.yaml) whose values have no natural "higher": which species are present.
UNDIRECTED = {"community_composition"}
UNDIRECTED_WORDS = re.compile(r"\b(composition|similarity|dissimilarity|ordination|make up|assemblages?)\b", re.I)
PARTICLES = {"van", "von", "de", "der", "den", "del", "della", "di", "da", "du", "das", "dos", "la", "le", "st",
             "st.", "ten", "ter", "mac", "mc", "o"}  # fmt: skip
INITIALS = re.compile(r"^(?:[A-Z]\.?\s*-?)+$")


def _fix_case(name: str) -> str:
    """Title-case an all-caps surname ("McLACHLAN" -> "McLachlan", "O'BRIEN" -> "O'Brien")."""
    letters = [c for c in name if c.isalpha()]
    if len(letters) < 3 or sum(c.isupper() for c in letters) <= len(letters) // 2 + 1:
        return name

    def word(w: str) -> str:
        w = w.lower().capitalize()
        if w.startswith("Mc") and len(w) > 2:
            w = "Mc" + w[2:].capitalize()
        if w.startswith("O'") and len(w) > 2:
            w = "O'" + w[2:].capitalize()
        return w

    return re.sub(r"[^\s-]+", lambda m: word(m.group(0)), name)


def _surname(first: str, has_comma_part: bool, after: str) -> str:
    """Drop given names left in the surname slot: "Anne Naeth" (no comma), "Anne Naeth, M." (initials after
    the comma). Multi-word surnames with a particle ("Van Wieren", "Das Gupta") and real double surnames
    followed by a given name ("Grégoire Taillefer, Amélie") are kept."""
    toks = first.split()
    if len(toks) < 2 or toks[0].lower() in PARTICLES:
        return first
    if not has_comma_part or INITIALS.match(after.strip()):
        return toks[-1]
    return first


def _first_author(authors) -> str:
    """Surname of the first author: text before the first comma. `authors` is a list in the graph but
    may arrive as its string repr ("['Strack, Maria', ...]") or a plain string."""
    if isinstance(authors, str):
        s = authors.strip()
        if s.startswith("["):
            try:
                authors = ast.literal_eval(s)
            except (ValueError, SyntaxError):
                authors = [s.strip("[]").split("'")[1] if "'" in s else s.strip("[]")]
        else:
            authors = [s.split(";")[0]]
    if not isinstance(authors, (list, tuple)) or not authors:
        return ""
    first = authors[0]
    if isinstance(first, dict):  # defensive: {"name": ...} style records
        first = first.get("family") or first.get("name") or ""
    if not isinstance(first, str):
        return ""
    head, comma, after = first.partition(",")
    name = head.strip().strip("'\"[] ")
    return _fix_case(_surname(name, bool(comma), after))


def short_cite(doc_id: str, ctx: Context) -> str:
    doc = ctx.graph.docs.get(doc_id) or {}
    surname = _first_author(doc.get("authors"))
    year = doc.get("year")
    if surname:
        return f"{surname} {year}" if isinstance(year, (int, str)) and str(year).strip() else f"{surname} n.d."
    doi = doc.get("doi")
    return doi if isinstance(doi, str) and doi.strip() else (doc_id or "unknown study")


def cite_labels(doc_ids: list[str], ctx: Context) -> dict[str, str]:
    """doc_id -> "Surname Year", with a/b/... appended only where two studies share a label."""
    base = {d: short_cite(d, ctx) for d in doc_ids}
    by_label: dict[str, list[str]] = defaultdict(list)
    for d in sorted(base):
        by_label[base[d]].append(d)
    out = {}
    for label, ds in by_label.items():
        for i, d in enumerate(ds):
            out[d] = f"{label}{chr(ord('a') + i) if i < 26 else i}" if len(ds) > 1 else label
    return out


def _studies(n: int) -> str:
    return f"{n} {'study' if n == 1 else 'studies'}"


def breakdown(verdict: Verdict, associational: bool, ctx: Context) -> str:
    docs = list(verdict.doc_effects)
    if not docs:
        return ""
    labels = cite_labels([d for d, _ in docs], ctx)
    groups: dict[int | None, list[str]] = defaultdict(list)
    for d, e in docs:
        groups[e if e in ORDER else None].append(labels[d])
    words = ASSOC_GROUP if associational else CAUSAL_GROUP
    ordered = sorted(groups, key=lambda e: (-len(groups[e]), ORDER.index(e)))
    parts = []
    for i, e in enumerate(ordered):
        names = sorted(groups[e])
        shown = "; ".join(names[:MAX_NAMES]) + (f"; +{len(names) - MAX_NAMES} more" if len(names) > MAX_NAMES else "")
        n = len(names)
        verb = ("reports " if n == 1 else "report ") if i == 0 else ""
        parts.append(f"{n} {verb}{words[e]} ({shown})")
    body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Across {_studies(len(docs))}: {body}."


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def headline(direction: str, certainty: Certainty | None, cause: str, outcome: str, outcome_named: bool,
             associational: bool, doc_effects: tuple = (), plural: bool = False,
             undirected: bool = False) -> str:  # fmt: skip
    """The verdict sentence. The certainty is its only hedge, and it is stated once in words. `plural`: X
    takes plural verbs. `undirected`: Y has no natural direction, so a sign is "a change in Y"."""

    def agree(singular: str, pl: str) -> str:
        return pl if plural else singular

    tag = f"{certainty.replace('_', ' ')} certainty" if certainty else "certainty not graded"
    if associational:
        tag += "; associational evidence only"
    mod = CERTAINTY_MODIFIER.get(certainty or "", "")
    rel = f"association between {cause} and {outcome}" if associational else f"effect of {cause} on {outcome}"
    lean = (ASSOC_GROUP if associational else CAUSAL_GROUP)[SIGN[direction]] if direction in SIGN else ""
    n_docs = len(doc_effects)
    disagree = len({e for _, e in doc_effects if e is not None}) > 1  # studies with different signs
    mixed_clause = ("the studies disagree" if disagree else "the one study reports mixed results" if n_docs == 1
                    else "the results are mixed")  # fmt: skip
    higher = {"increase": "higher", "decrease": "lower"}.get(direction, "")
    if higher and outcome_named and outcome.lower().startswith("the "):
        what = f"a {higher} {outcome[4:]}"  # "a higher number of species", not "higher the number"
    else:
        what = (f"{higher} {outcome}" if outcome_named else f"{higher} values of {outcome}") if higher else ""
    if undirected and higher:
        what, lean = f"a change in {outcome}", f"a change in {outcome}"
    if certainty == "very_low":
        # schema: very_low has no verb modifier and its own template
        lead = (f"The evidence is very uncertain about the {rel}" if associational
                else VERY_LOW_TEMPLATE.format(subject=cause, object=outcome))  # fmt: skip
        if associational and what:  # D1: "is associated with" for every all-associational direction
            return f"{lead}, but it points to {cause} being associated with {what} ({tag})."
        if lean:
            return f"{lead}, but it points to {lean} ({tag})."
        tail = mixed_clause if direction == "mixed" else "no direction can be read from it"
        return f"{lead}, and {tail} ({tag})."
    if direction in ("increase", "decrease"):
        if associational:
            be = {"probably": agree("is", "are") + " probably", "may": "may be"}.get(mod, agree("is", "are"))
            return f"{_cap(cause)} {be} associated with {what} ({tag})."
        third, base = ("changes", "change") if undirected else VERB[direction]
        third = agree(third, base)
        verb = f"may {base}" if mod == "may" else f"{mod} {third}".strip()
        return f"{_cap(cause)} {verb} {outcome} ({tag})."
    if direction == "no_effect":  # a null is a direction too, so it takes the modifier (one hedge source)
        if associational:
            verb = {"probably": "probably " + agree("shows", "show"), "may": "may show"}.get(
                mod, agree("shows", "show")
            )
            return f"{_cap(cause)} {verb} no detectable association with {outcome} ({tag})."
        verb = {"probably": "probably " + agree("has", "have"), "may": "may have"}.get(mod, agree("has", "have"))
        return f"{_cap(cause)} {verb} no detectable effect on {outcome} ({tag})."
    if direction == "mixed":
        if disagree:
            return f"Studies disagree about the {rel} ({tag})."
        if n_docs == 1:
            return f"The one study on the {rel} reports mixed results ({tag})."
        return f"Results on the {rel} are mixed ({tag})."
    return f"The direction of the {rel} is unclear ({tag})."


def unclear_note(verdict: Verdict) -> str:
    """For `unclear` with no study-level vote: say why, without a count that could disagree with doc_effects."""
    if verdict.direction == "unclear" and not verdict.doc_effects:
        return "None of the linked claims gives a usable direction."
    return ""


@register("renderer", "faithful")
class FaithfulRenderer(SearchedRenderer):
    def render(
        self, verdict: Verdict, candidates: Candidates, certainty: Certainty | None, ctx: Context
    ) -> tuple[str, str | None]:
        if verdict.status == "no_evidence":
            return super().render(verdict, candidates, certainty, ctx)
        try:
            return self.answered(verdict, candidates, certainty, ctx), None
        except Exception:  # noqa: BLE001 - the renderer must never raise; fall back to baseline wording
            return super().render(verdict, candidates, certainty, ctx)

    @staticmethod
    def answered(verdict: Verdict, candidates: Candidates, certainty: Certainty | None, ctx: Context) -> str:
        f = candidates.frame
        q = f.parsed.question.text or ""
        cause, cause_label = phrase(f.cause, ctx, q, "the intervention")
        outcome, _ = phrase(f.outcome, ctx, q, "the outcome")
        included = verdict.included
        associational = bool(included) and all(is_associational(v, ctx) for v in included)
        undirected = bool(f.outcome.classes and f.outcome.classes[0].id in UNDIRECTED) or bool(
            UNDIRECTED_WORDS.search(outcome) or UNDIRECTED_WORDS.search(f.outcome.text or "")
        )
        head = headline(verdict.direction or "unclear", certainty, cause, outcome, outcome != "the outcome",
                        associational, verdict.doc_effects, plural=is_plural(cause, cause_label),
                        undirected=undirected)  # fmt: skip
        rest = [s for s in (breakdown(verdict, associational, ctx), unclear_note(verdict)) if s]
        return " ".join([head, *rest])
