"""Item 15: renderer `faithful`. Unit tests on constructed verdicts, then an overclaim sweep over every
cause x outcome class pair of the real taxonomy under two engines (defaults and the item 6/11/13 engine)."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from camoreasoning import registry
from camoreasoning.components import Context
from camoreasoning.config import Settings
from camoreasoning.contracts import Candidates, EdgeVote, Frame, ParsedQuestion, Question, Ref, Side, Verdict
from camoreasoning.llm import LLM
from camoreasoning.strategies.grader.rubric import is_associational
from camoreasoning.strategies.renderer.faithful import MAX_NAMES, _first_author, cite_labels, short_cite
from camoreasoning.taxonomy import load_taxonomy

R = registry.get("renderer", "faithful")
CERT = re.compile(r"\((high|moderate|low|very low) certainty")
ACROSS = re.compile(r"Across (\d+) stud(?:y|ies): ")
CAUSAL = re.compile(r"\b(causes?|caused|causing|increases?|increased|decreases?|decreased|leads? to|reduces?|"
                    r"reduced|raises?|raised|improves?|improved|effects?|affects?|drives?)\b", re.I)  # fmt: skip
EXTRA_HEDGES = re.compile(r"\b(might|possibly|perhaps|could|likely|suggests?|appears?|seems?|potentially)\b", re.I)

DOCS = {
    "d:strack": {"authors": ["Strack, Maria", "Keith, Arnold Magnus"], "year": 2014, "doi": "10.1/strack"},
    "d:smith1": {"authors": "['Smith, Ann', 'Lee, Bo']", "year": 2014},
    "d:smith2": {"authors": ["Smith, Carl"], "year": 2014},
    "d:lee": {"authors": ["Lee, Dan"], "year": 2018},
    "d:ortiz": {"authors": ["Ortiz, Eva"], "year": 2020},
    "d:noyear": {"authors": ["Kim, Jo"], "year": None},
    "d:noauthor": {"authors": [], "year": 2001, "doi": "10.9/anon"},
    "d:bare": {},
}


def fake_ctx(edges: dict | None = None):
    return SimpleNamespace(graph=SimpleNamespace(docs=DOCS, edges=edges or {}, nodes={}))


def cands(cause: str | None = "prescribed burning", outcome: str | None = "native plant richness") -> Candidates:
    q = Question("q", f"What effect does {cause} have on {outcome}?")
    f = Frame(ParsedQuestion(q, cause, outcome, True), Side(cause, (Ref("c"),)), Side(outcome, (Ref("o"),)),
              "regex", 1.0)  # fmt: skip
    return Candidates(f, {"n1": 1}, {"n2": 1}, forward=("e",))


def verdict(direction: str, docs: list[tuple[str, int | None]], assoc: bool = False) -> Verdict:
    reason = "associational" if assoc else "signed"
    votes = tuple(EdgeVote(f"e{i}", d, e, True, reason) for i, (d, e) in enumerate(docs))
    return Verdict("answered", direction, votes, tuple(docs), 0.5)


def render(v: Verdict, certainty, c: Candidates | None = None, ctx=None) -> str:
    text, searched = R.render(v, c or cands(), certainty, ctx or fake_ctx())
    assert searched is None and text
    return text


def check_invariants(text: str, v: Verdict, certainty, assoc: bool, cause: str, outcome: str) -> None:
    """The overclaim rules every answered text must satisfy."""
    assert text.strip()
    phrases = CERT.findall(text)
    assert len(phrases) == 1, text
    if certainty:
        assert phrases[0] == certainty.replace("_", " "), text
    m = ACROSS.findall(text)
    if v.doc_effects:
        assert m == [str(len(v.doc_effects))], text
        body = text.split(": ", 1)[1]
        groups = re.findall(r"(?:^|, | and )(\d+) (?:reports? )?(?:an? |no |mixed )", body)
        assert sum(map(int, groups)) == len(v.doc_effects), text
    else:
        assert not m, text
    bare = text.replace(cause, "").replace(cause[:1].upper() + cause[1:], "").replace(outcome, "")
    assert not EXTRA_HEDGES.search(bare), text
    head = bare.split(" Across ")[0]
    hedges = {" may ": "low", "probably": "moderate", "very uncertain": "very_low"}
    used = [w for w in hedges if w in head]
    assert all(hedges[w] == certainty for w in used), text  # a modifier never contradicts the stated certainty
    if certainty in ("moderate", "low", "very_low") and (v.direction in ("increase", "decrease", "no_effect")
                                                         or certainty == "very_low"):  # fmt: skip
        assert used, text  # every stated direction (nulls too) carries the schema modifier / very_low template
    if assoc:
        assert not CAUSAL.search(bare), text
        assert "associational evidence only" in text
        if v.direction in ("increase", "decrease"):
            assert "associated with" in text
    if v.direction in ("no_effect", "mixed", "unclear"):
        assert not re.search(r"\b(increases?|decreases?|higher|lower)\b", head), text
    if v.direction == "no_effect":
        assert "no detectable" in head
    if len(v.doc_effects) == 1:
        assert not re.match(r"Studies\b", text), text  # one counted study is never "studies"


# --- unit tests -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("certainty", "verb"),
    [("high", "Prescribed burning increases native plant richness (high certainty)."),
     ("moderate", "Prescribed burning probably increases native plant richness (moderate certainty)."),
     ("low", "Prescribed burning may increase native plant richness (low certainty)."),
     ("very_low", "The evidence is very uncertain about the effect of prescribed burning on native plant richness, "
                  "but it points to an increase (very low certainty).")],
)  # fmt: skip
def test_increase_one_hedge_per_certainty(certainty, verb):
    v = verdict("increase", [("d:lee", 1), ("d:ortiz", 1), ("d:strack", 0), ("d:smith2", 1)])
    text = render(v, certainty)
    assert text == (f"{verb} Across 4 studies: 3 report an increase (Lee 2018; Ortiz 2020; Smith 2014) "
                    "and 1 no detectable effect (Strack 2014).")  # fmt: skip
    check_invariants(text, v, certainty, False, "prescribed burning", "native plant richness")


def test_decrease():
    v = verdict("decrease", [("d:lee", -1), ("d:ortiz", -1)])
    text = render(v, "moderate")
    assert text.startswith("Prescribed burning probably decreases native plant richness (moderate certainty).")
    assert "Across 2 studies: 2 report a decrease (Lee 2018; Ortiz 2020)." in text


def test_no_effect_is_not_a_decrease():
    v = verdict("no_effect", [("d:lee", 0), ("d:ortiz", 0), ("d:strack", -1)])
    text = render(v, "low")
    assert text.startswith("Prescribed burning may have no detectable effect on native plant richness (low certainty).")
    assert "2 report no detectable effect (Lee 2018; Ortiz 2020) and 1 a decrease (Strack 2014)" in text
    check_invariants(text, v, "low", False, "prescribed burning", "native plant richness")


@pytest.mark.parametrize(
    ("certainty", "assoc", "start"),
    [("high", False, "Prescribed burning has no detectable effect on"),
     ("moderate", False, "Prescribed burning probably has no detectable effect on"),
     ("low", True, "Prescribed burning may show no detectable association with"),
     ("very_low", False, "The evidence is very uncertain about the effect of prescribed burning on native plant "
                         "richness, but it points to no detectable effect")],
)  # fmt: skip
def test_null_carries_the_certainty_modifier(certainty, assoc, start):
    """review_20 rounds 1-2 (R03, R08, R13): "Studies found no detectable effect (moderate certainty)" read as
    unhedged, and "Studies" over one counted study overstated it. A null is a direction; it takes the modifier."""
    v = verdict("no_effect", [("d:lee", 0)], assoc=assoc)
    text = render(v, certainty)
    assert text.startswith(start), text
    check_invariants(text, v, certainty, assoc, "prescribed burning", "native plant richness")


def test_mixed_says_studies_disagree_and_gives_breakdown():
    v = verdict("mixed", [("d:lee", 1), ("d:ortiz", -1), ("d:strack", None)])
    text = render(v, "low")
    assert text.startswith("Studies disagree about the effect of prescribed burning on native plant richness")
    assert "1 reports an increase (Lee 2018), 1 a decrease (Ortiz 2020) and 1 mixed results within the study " \
           "(Strack 2014)" in text  # fmt: skip
    check_invariants(text, v, "low", False, "prescribed burning", "native plant richness")


def test_mixed_from_one_internally_tied_study_does_not_say_studies_disagree():
    v = verdict("mixed", [("d:lee", None)])
    text = render(v, "very_low")
    assert "disagree" not in text and "the one study reports mixed results" in text
    v2 = verdict("mixed", [("d:lee", None), ("d:ortiz", None)])
    assert "Results on the effect" in render(v2, "low") and "disagree" not in render(v2, "low")


def test_unclear_with_and_without_study_votes():
    v = verdict("unclear", [("d:lee", None)])
    text = render(v, "low")
    assert text.startswith("The direction of the effect of prescribed burning on native plant richness is unclear")
    assert "Across 1 study: 1 reports mixed results within the study (Lee 2018)." in text
    empty = Verdict("answered", "unclear", (EdgeVote("e1", "d:lee", None, True, "unsigned"),), (), 0.0)
    text = render(empty, "low")
    assert "Across" not in text and "None of the linked claims gives a usable direction." in text


@pytest.mark.parametrize(
    ("direction", "certainty", "start"),
    [("increase", "low", "Prescribed burning may be associated with higher native plant richness "
                         "(low certainty; associational evidence only)."),
     ("decrease", "moderate", "Prescribed burning is probably associated with lower native plant richness "
                              "(moderate certainty; associational evidence only)."),
     ("increase", "very_low", "The evidence is very uncertain about the association between prescribed burning and "
                              "native plant richness, but it points to prescribed burning being associated with higher "
                              "native plant richness (very low certainty; associational evidence only)."),
     ("no_effect", "low", "Prescribed burning may show no detectable association with native plant richness "
                          "(low certainty; associational evidence only)."),
     ("mixed", "very_low", "The evidence is very uncertain about the association between prescribed burning and "
                           "native plant richness, and the studies disagree (very low certainty; associational "
                           "evidence only).")],
)  # fmt: skip
def test_all_associational_never_uses_causal_wording(direction, certainty, start):
    effects = {"increase": [1, 1], "decrease": [-1, -1], "no_effect": [0, 0], "mixed": [1, -1]}[direction]
    v = verdict(direction, list(zip(["d:lee", "d:ortiz"], effects)), assoc=True)
    text = render(v, certainty)
    assert text.startswith(start), text
    group = {"increase": "a positive association", "decrease": "a negative association",
             "no_effect": "no detectable association", "mixed": "a negative association"}[direction]  # fmt: skip
    assert group in text
    check_invariants(text, v, certainty, True, "prescribed burning", "native plant richness")


def test_partly_associational_keeps_causal_verb_per_d1():
    v = Verdict("answered", "increase", (EdgeVote("e1", "d:lee", 1, True, "associational"),
                                         EdgeVote("e2", "d:ortiz", 1, True, "signed")),
                (("d:lee", 1), ("d:ortiz", 1)), 1.0)  # fmt: skip
    text = render(v, "low")
    assert "may increase" in text and "associational evidence only" not in text


def test_associational_read_from_graph_predicate():
    ctx = fake_ctx({"e0": {"predicate": "correlated_with"}})
    v = Verdict("answered", "increase", (EdgeVote("e0", "d:lee", 1, True, "signed"),), (("d:lee", 1),), 1.0)
    assert "associated with higher" in render(v, "low", ctx=ctx)


def test_single_study():
    v = verdict("increase", [("d:strack", 1)])
    text = render(v, "low")
    assert text.endswith("Across 1 study: 1 reports an increase (Strack 2014).")


def test_truncation_after_max_names():
    docs = [("d:lee", 1), ("d:ortiz", 1), ("d:strack", 1), ("d:noyear", 1), ("d:bare", 1)]
    v = verdict("increase", docs)
    text = render(v, "moderate")
    assert f"+{len(docs) - MAX_NAMES} more)" in text and "Across 5 studies: 5 report an increase" in text
    assert text.count(";") == MAX_NAMES  # 3 names, then "; +2 more"


def test_identical_surname_year_get_suffixes_only_when_needed():
    ctx = fake_ctx()
    assert cite_labels(["d:smith1", "d:smith2"], ctx) == {"d:smith1": "Smith 2014a", "d:smith2": "Smith 2014b"}
    assert cite_labels(["d:smith1", "d:lee"], ctx) == {"d:smith1": "Smith 2014", "d:lee": "Lee 2018"}
    v = verdict("increase", [("d:smith1", 1), ("d:smith2", 1)])
    assert "(Smith 2014a; Smith 2014b)" in render(v, "low")


def test_missing_doc_metadata_falls_back():
    ctx = fake_ctx()
    assert short_cite("d:noyear", ctx) == "Kim n.d."
    assert short_cite("d:noauthor", ctx) == "10.9/anon"
    assert short_cite("d:bare", ctx) == "d:bare"
    assert short_cite("d:absent", ctx) == "d:absent"
    v = verdict("increase", [("d:absent", 1), ("d:bare", 1), ("d:noauthor", 1)])
    text = render(v, "low")
    assert "Across 3 studies" in text and "10.9/anon" in text and "d:absent" in text


@pytest.mark.parametrize(
    ("authors", "surname"),
    [(["Strack, Maria", "Keith, Arnold"], "Strack"), ("['Strack, Maria', 'Keith, Arnold Magnus']", "Strack"),
     ('["D\'Astous, A."]', "D'Astous"), ("Strack, Maria; Keith, A.", "Strack"), ("[]", ""), ([], ""), (None, ""),
     ("['unterminated", "unterminated"), ([None], ""), ("Organisation Name", "Organisation Name")],
)  # fmt: skip
def test_first_author_parsing_is_robust(authors, surname):
    assert _first_author(authors) == surname


def test_unparsed_spans_and_odd_inputs_never_raise():
    v = verdict("increase", [("d:lee", 1)])
    text = render(v, None, cands(None, None))
    assert text.startswith("The intervention increases the outcome (certainty not graded).")
    weird = Verdict("answered", None, (), (("d:lee", 7),), 0.0)  # type: ignore[arg-type]
    assert render(weird, "low")


def test_no_evidence_path_is_searched_unchanged(make_ctx):
    ctx = make_ctx()
    c = Candidates(Frame(ParsedQuestion(Question("q", "x"), "moon", "y", True), Side("moon"), Side("y"), "regex", 1.0),
                   {}, {})  # fmt: skip
    v = Verdict("no_evidence", None, ())
    assert R.render(v, c, None, ctx) == registry.get("renderer", "searched").render(v, c, None, ctx)


# --- overclaim sweep over every class pair --------------------------------------------------------

ENGINES = {
    "default": {"interpreter": "baseline", "aggregator": "baseline", "grader": "baseline"},
    "B": {"interpreter": "sentence", "aggregator": "studies", "grader": "rubric"},
}


@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_overclaim_sweep_every_class_pair(engine, graph, tmp_path):
    tax = load_taxonomy()
    ctx = Context(graph, tax, LLM(Settings()), Settings(), tmp_path)
    s = {st: registry.get(st, n) for st, n in ENGINES[engine].items()}
    retr = registry.get("retriever", "baseline")
    causes = [c for c in tax.classes.values() if c.kind in ("cause", "both")]
    outcomes = [c for c in tax.classes.values() if c.kind in ("outcome", "both")]
    n_answered, n_assoc, seen = 0, 0, set()
    for c in causes:
        for o in outcomes:
            if c.id == o.id:
                continue
            cause, outcome = c.label.lower(), o.label.lower()
            q = Question("q", f"What effect does {cause} have on {outcome}?")
            frame = Frame(ParsedQuestion(q, cause, outcome, True), Side(cause, (Ref(c.id),)),
                          Side(outcome, (Ref(o.id),)), "regex", 1.0)  # fmt: skip
            cands_ = retr.retrieve(frame, ctx)
            if not cands_.forward:
                continue
            v = s["aggregator"].aggregate(s["interpreter"].interpret(cands_, ctx), cands_, ctx)
            if v.status != "answered":
                continue
            certainty = s["grader"].grade(v, ctx)
            text, searched = R.render(v, cands_, certainty, ctx)
            assert searched is None
            assoc = all(is_associational(x, ctx) for x in v.included)
            check_invariants(text, v, certainty, assoc, cause, outcome)
            n_answered += 1
            n_assoc += assoc
            seen.add((v.direction, assoc))
    assert n_answered > 500 and n_assoc > 50  # the sweep actually covers the graph
    assert {("increase", True), ("mixed", False), ("no_effect", False)} <= seen


def test_trap_null_text(graph, make_ctx):
    """'k was lower, but not significantly different than at fen sites' must not read as a decrease."""
    from tests.strategies.test_traps import ENGINE, ask, ends

    assert ENGINE["renderer"] == "faithful"
    r = ask(graph, make_ctx(), *ends(graph, "camo:edge_20171069c1db"))
    assert "no detectable" in r.text and not re.search(r"\b(decreases?|lower|negative)\b", r.text)


# --- upstream overclaims found by the review_20 audit (round 1). Not renderer wording: the text renders
# the verdict faithfully, but the verdict misreads the sentence. Strict xfail so a fix upstream flips them.


@pytest.mark.xfail(strict=True, reason="R20: 'No Barrier' (absence of protection) is labelled +1 in tree_protection")
def test_review_no_barrier_node_is_not_protection():
    tax = load_taxonomy()
    node = "camo:node_1352a634368d"  # "No Barrier forest floor protection treatment"
    assert all(lb.polarity != 1 for lb in tax.labels if lb.node_id == node and lb.class_id == "tree_protection")


@pytest.mark.xfail(strict=True, reason="R08/R18: CAMO stores a p=1e-6 association as [unchanged], read as a null")
def test_review_significant_association_is_not_a_null(graph, make_ctx):
    from tests.strategies.test_traps import ask, ends

    r = ask(graph, make_ctx(), *ends(graph, "camo:edge_e31b596f68eb"))
    assert r.verdict.direction != "no_effect"


@pytest.mark.xfail(strict=True, reason="R07: CAMO edge says clearcut [decreased] evenness; the sentence says the "
                                       "reference forests were least even, i.e. clearcuts higher")  # fmt: skip
def test_review_least_even_in_reference_is_higher_in_clearcuts(graph, make_ctx):
    from tests.strategies.test_traps import ask, ends

    r = ask(graph, make_ctx(), *ends(graph, "camo:edge_eadd32061916"))
    assert r.verdict.direction == "increase"
