"""Item 7: the trap suite. One end-to-end engine run per trap on real graph edges.

Chain: retriever `baseline` -> interpreter `sentence` -> aggregator `studies` -> grader `rubric` ->
citer `precise` -> renderer `faithful`. The linker is bypassed: each question is a Frame naming the
graph nodes directly, with the polarity a node label would give (the node's qualifier sign). Expected
answers come from the quoted `original_sentence`. Trap keys match experiments/results/trap_inventory.json
and the `trap:<key>` tags dev items should carry (experiments/traps/README.md).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import pytest

from camoreasoning import registry
from camoreasoning.contracts import Frame, ParsedQuestion, Question, Ref, Side, Verdict
from camoreasoning.signs import qualifier_sign
from camoreasoning.taxonomy import load_taxonomy

ENGINE = {"retriever": "baseline", "interpreter": "sentence", "aggregator": "studies", "grader": "rubric",
          "citer": "precise", "renderer": "faithful"}  # fmt: skip


@dataclass
class Result:
    verdict: Verdict
    certainty: str | None
    edge_ids: list[str]
    text: str
    searched: str | None


def pol(graph, node_id: str) -> int:
    return qualifier_sign(graph.nodes[node_id].get("state_or_change_qualifier")) or 0


def ask(graph, ctx, causes, outcomes, cause_pol=None) -> Result:
    """Ask "what effect does <causes> have on <outcomes>?" at node level and run the engine."""
    s = {st: registry.get(st, n) for st, n in ENGINE.items()}
    ref = lambda n, p=None: Ref(n, pol(graph, n) if p is None else p)  # noqa: E731
    cause = Side("cause", nodes=tuple(ref(n, cause_pol) for n in causes))
    outcome = Side("outcome", nodes=tuple(ref(n) for n in outcomes))
    q = Question("trap", "What effect does cause have on outcome?")
    cands = s["retriever"].retrieve(Frame(ParsedQuestion(q, "cause", "outcome", True), cause, outcome, "regex", 1.0),
                                    ctx)  # fmt: skip
    verdict = s["aggregator"].aggregate(s["interpreter"].interpret(cands, ctx), cands, ctx)
    certainty = s["grader"].grade(verdict, ctx)
    cited = s["citer"].cite(verdict, ctx) if verdict.status == "answered" else []
    text, searched = s["renderer"].render(verdict, cands, certainty, ctx)
    return Result(verdict, certainty, cited, text, searched)


def ends(graph, eid: str) -> tuple[list[str], list[str]]:
    e = graph.edges[eid]
    return [e["subject"]], [e["object"]]


@pytest.fixture
def ctx(make_ctx):
    return make_ctx()


def test_reversed_edges(graph, ctx):
    """A question asked backwards. Graph: caging -> breakage. Asked: breakage -> caging."""
    s, o = ends(graph, "camo:edge_898ca6605bdd")
    r = ask(graph, ctx, o, s)
    assert r.verdict.status == "no_evidence" and r.edge_ids == []
    assert "camo:edge_898ca6605bdd" in r.searched and "the other way" in r.text


def test_null_is_not_decrease(graph, ctx):
    """'k was lower, but not significantly different than at fen sites': no_effect, not decrease."""
    r = ask(graph, ctx, *ends(graph, "camo:edge_20171069c1db"))
    assert (r.verdict.status, r.verdict.direction) == ("answered", "no_effect")
    assert r.edge_ids == ["camo:edge_20171069c1db"] and "no detectable" in r.text  # "effect" or, D1, "association"
    assert not re.search(r"\b(decreases?|lower|negative)\b", r.text)


def test_associational_is_not_causal(graph, ctx):
    """'Water table position was significantly positively related to graminoid cover' (correlated_with)."""
    eid = "camo:edge_9ab77deefcdf"
    r = ask(graph, ctx, *ends(graph, eid))
    assert r.verdict.direction == "increase" and "all_associational" in r.verdict.notes
    grades = ["very_low", "low", "moderate"]
    edge_grade = graph.edges[eid]["certainty_grade"]
    assert r.certainty == grades[max(0, grades.index(edge_grade) - 1)]  # D4: one level lower


def test_associational_answer_text_never_says_causes(graph, ctx):
    """D1: every included vote is associational, so the text says "associated with", never a causal verb."""
    r = ask(graph, ctx, *ends(graph, "camo:edge_9ab77deefcdf"))
    assert "associated with" in r.text
    body = r.text.replace("cause", "X").replace("outcome", "Y")  # the frame's span texts are literally these
    assert not re.search(r"\b(causes?|increases?|decreases?|leads? to|reduces?|raises?|improves?|effects?)\b", body)


def test_negative_subject_qualifier(graph, ctx):
    """'Black spruce and jack pine height increased when Kalmia was controlled with herbicide':
    [decreased] Kalmia causes [increased] height, so Kalmia decreases height."""
    r = ask(graph, ctx, *ends(graph, "camo:edge_f2c1bfb5b95f"))
    assert r.verdict.direction == "decrease"


def test_asking_about_the_removal_flips_back(graph, ctx):
    """Same edge, asked as 'Kalmia control' (polarity -1 on the Kalmia node): height increases."""
    s, o = ends(graph, "camo:edge_f2c1bfb5b95f")
    r = ask(graph, ctx, s, o, cause_pol=-pol(graph, s[0]))
    assert r.verdict.direction == "increase"


def test_unchanged_outcome_is_a_null(graph, ctx):
    """'Soil exchangeable K levels ... remained relatively stable during the chronosequence.'"""
    r = ask(graph, ctx, *ends(graph, "camo:edge_07b5d3056850"))
    assert r.verdict.direction == "no_effect"


def test_significant_unchanged_outcome_is_not_a_null(graph, ctx):
    """'Seeding method was associated with richness ... (F=112.04, P=0.000)', object [unchanged] Richness:
    a significant difference in an unstated direction gives no vote, never 'no detectable effect'."""
    r = ask(graph, ctx, *ends(graph, "camo:edge_c641160f3447"))
    assert r.verdict.status == "no_evidence" and "no detectable" not in r.text
    assert [v.reason for v in r.verdict.votes] == ["unsigned_difference"]
    assert "without saying which way" in r.searched


@pytest.mark.parametrize(
    ("value", "significant"),
    [("p < 0.001", True), ("F=112.04, P=0.000", True), ("T = -17.98, A = 0.14, p < 10^-6", True),
     ("significantly different", True), ("p = 0.06", False), ("not significant", False), ("38.0%", False),
     ("", False), (None, False), (7, False)],
)  # fmt: skip
def test_reports_significance(value, significant):
    from camoreasoning.strategies.interpreter.sentence import reports_significance

    assert reports_significance({"strength": {"quantitative_value": value}}) is significant


def test_reference_locus_needs_the_reference_as_the_only_locus(graph):
    """R07: 'grasses were least evenly distributed in reference forests' -> clearcuts higher. The same
    sentence with a two-arm comparison, or with the qualifier already inverted, is left as annotated."""
    from camoreasoning.strategies.interpreter.sentence import read_edge, reference_locus

    e = graph.edges["camo:edge_eadd32061916"]
    s, o = graph.nodes[e["subject"]], graph.nodes[e["object"]]
    assert reference_locus(e, s, o)
    assert read_edge(e, o, 1, -1, s) == (1, True, "reference_locus")
    assert read_edge(e, o, 1, -1) == (-1, True, "associational")  # no subject given: rule 8 is off
    two_arm = {**e, "original_sentence": "grasses were less even in clearcuts than in reference forests."}
    assert not reference_locus(two_arm, s, o)
    assert not reference_locus(e, s, {**o, "state_or_change_qualifier": "increased"})
    assert not reference_locus(e, {**s, "entity_type": "environmental_variable"}, o)


def test_prevented_change_is_not_a_null(graph, ctx):
    """'community diversity increased ... except adaptable-mix': prevents [unchanged] is not 'no effect'."""
    r = ask(graph, ctx, *ends(graph, "camo:edge_41a7453a63ad"))
    assert r.verdict.status == "no_evidence" and "prevented a change" in r.searched


def test_double_negation(graph, ctx):
    """'Caging significantly decreased breakage' stored as caging prevents [decreased] breakage."""
    r = ask(graph, ctx, *ends(graph, "camo:edge_898ca6605bdd"))
    assert r.verdict.direction == "decrease" and "double_negation" in r.verdict.notes


def test_twin_edges_are_one_study(graph, ctx):
    """'Organic C levels increased ... following establishment of Young Plantations ...': two edges, one
    sentence, one study. The verdict counts one study; both edges are cited."""
    twins = ["camo:edge_82cc8c02077b", "camo:edge_ae6455b59571"]
    assert len({graph.edges[e]["original_sentence"] for e in twins}) == 1
    causes = [graph.edges[e]["subject"] for e in twins]
    outcomes = sorted({graph.edges[e]["object"] for e in twins})
    r = ask(graph, ctx, causes, outcomes)
    assert len(r.verdict.doc_effects) == 1 and r.verdict.direction == "increase"
    assert set(twins) <= set(r.edge_ids)


def test_twins_that_disagree_make_a_mixed_study(graph, ctx):
    """One sentence, one null twin and one signed twin, same study and nothing else: mixed, not a win."""
    groups = defaultdict(list)
    for eid, e in graph.edges.items():
        groups[(e["source_document"], e.get("original_sentence"))].append(eid)
    for ids in groups.values():
        if len(ids) != 2:
            continue
        a, b = (graph.edges[i] for i in ids)
        if bool(a.get("negated")) == bool(b.get("negated")) or {a["predicate"], b["predicate"]} != {"causes"}:
            continue
        signed = b if a.get("negated") else a
        if any(pol(graph, signed[k]) != 1 for k in ("subject", "object")):
            continue
        r = ask(graph, ctx, [a["subject"], b["subject"]], [a["object"], b["object"]])
        doc_votes = [e for d, e in r.verdict.doc_effects if d == a["source_document"]]
        if len(r.verdict.doc_effects) == 1 and doc_votes == [None]:
            assert r.verdict.direction == "mixed" and set(ids) <= set(r.edge_ids)
            return
    pytest.skip("no clean null/signed twin pair found")


def test_moderators_and_mediators_do_not_vote(graph, ctx):
    """'there was significant interactions with OM thickness and seedbed type' (moderates)."""
    r = ask(graph, ctx, *ends(graph, "camo:edge_fda831dab2ed"))
    assert r.verdict.status == "no_evidence" and "without a direction" in r.searched


def test_reference_comparator_is_flagged(graph, ctx):
    """Restored vs unrestored/undisturbed sites: the verdict carries the flag so wording can say so."""
    r = ask(graph, ctx, *ends(graph, "camo:edge_e764a1d31956"))
    assert r.verdict.status == "answered" and "reference_comparator" in r.verdict.notes


@pytest.mark.parametrize(
    ("a", "b"),
    [("native_abundance", "invasive_abundance"), ("tree_seedling_survival", "tree_growth"),
     ("plant_cover_total", "plant_richness")],
)  # fmt: skip
def test_near_miss_classes_stay_separate(a, b):
    """The taxonomy keeps near-miss concepts as distinct classes with distinct node sets."""
    tax = load_taxonomy()
    assert a in tax.classes and b in tax.classes
    na, nb = {lb.node_id for lb in tax.nodes_of(a)}, {lb.node_id for lb in tax.nodes_of(b)}
    assert na and nb and na != nb
    assert len(na & nb) < 0.2 * min(len(na), len(nb))


def test_time_is_not_an_intervention():
    """Time since disturbance is its own condition class, not part of any intervention class."""
    tax = load_taxonomy()
    assert "time_since_disturbance" in tax.classes
    time_nodes = {lb.node_id for lb in tax.nodes_of("time_since_disturbance")}
    for c in ("invasive_removal", "mulch_surface_cover"):
        assert not time_nodes & {lb.node_id for lb in tax.nodes_of(c)}
