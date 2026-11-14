"""Item 8: no_evidence per D3 (aggregator `studies`) and `searched_for` (renderer `searched`)."""

from __future__ import annotations

import pytest

from camoreasoning import registry
from camoreasoning.contracts import Candidates, Frame, ParsedQuestion, Question, Ref, Side
from camoreasoning.strategies.renderer.searched import MAX_IDS


def frame(cause: Side, outcome: Side) -> Frame:
    q = Question("q", f"What effect does {cause.text} have on {outcome.text}?")
    return Frame(ParsedQuestion(q, cause.text, outcome.text, True), cause, outcome, "regex", 1.0)


def run(cands: Candidates, ctx):
    votes = registry.get("interpreter", "sentence").interpret(cands, ctx)
    verdict = registry.get("aggregator", "studies").aggregate(votes, cands, ctx)
    text, searched = registry.get("renderer", "searched").render(verdict, cands, None, ctx)
    return verdict, text, searched


def edge_cands(graph, forward=(), reversed_=(), cause_pol=None):
    """Candidates over real edges, node polarities from their qualifiers (unchanged -> 0)."""
    from camoreasoning.signs import qualifier_sign

    def pol(n):
        return qualifier_sign(graph.nodes[n].get("state_or_change_qualifier")) or 0

    cause, outcome = {}, {}
    for e in forward:
        s, o = graph.edges[e]["subject"], graph.edges[e]["object"]
        cause[s] = pol(s) if cause_pol is None else cause_pol
        outcome[o] = pol(o)
    for e in reversed_:
        outcome.setdefault(graph.edges[e]["subject"], 1)
        cause.setdefault(graph.edges[e]["object"], 1)
    f = frame(Side("x", nodes=tuple(Ref(n) for n in cause)), Side("y", nodes=tuple(Ref(n) for n in outcome)))
    return Candidates(f, cause, outcome, tuple(forward), tuple(reversed_))


def test_unlinked_question_says_what_was_not_matched(make_ctx):
    ctx = make_ctx()
    c = Candidates(frame(Side("moon phase"), Side("seedling survival", (Ref("survival"),))), {}, {})
    verdict, text, searched = run(c, ctx)
    assert verdict.status == "no_evidence" and "could not match the question's cause" in text
    assert "'moon phase', which matched no class or node" in searched
    assert "Seedling survival (survival)" in searched


def test_class_pair_with_no_edges_names_classes_attributes_relation(make_ctx):
    ctx = make_ctx()
    retr = registry.get("retriever", "baseline")
    # find a fixture class pair with no edges either way
    for cause in ctx.taxonomy.of_kind("cause"):
        for outcome in ctx.taxonomy.of_kind("outcome"):
            f = frame(Side(cause.label, (Ref(cause.id),)), Side(outcome.label, (Ref(outcome.id),)))
            c = retr.retrieve(f, ctx)
            if not c.forward and not c.reversed:
                verdict, text, searched = run(c, ctx)
                assert verdict.status == "no_evidence"
                assert text == f"The graph has no claim that {cause.label} affects {outcome.label}."
                assert f"{cause.label} ({cause.id})" in searched and f"{outcome.label} ({outcome.id})" in searched
                assert "relation: any directional predicate from cause to outcome" in searched
                assert "Found 0 forward edges." in searched
                return
    pytest.skip("every fixture pair has edges")


def test_only_reversed_edges_are_named(graph, make_ctx):
    rev = [e for e in graph.edges if graph.edges[e].get("predicate") == "causes"][: MAX_IDS + 2]
    verdict, text, searched = run(edge_cands(graph, reversed_=rev), make_ctx())
    assert verdict.status == "no_evidence" and verdict.direction is None
    assert f"{len(rev)} claims run the other way" in text
    assert all(e in searched for e in rev[:MAX_IDS]) and rev[MAX_IDS] not in searched and ", ..." in searched


def test_only_moderators_say_no_direction(graph, make_ctx):
    # "interaction between seedbed type and organic matter thickness" moderates germination
    verdict, text, searched = run(edge_cands(graph, ["camo:edge_fda831dab2ed"]), make_ctx())
    assert verdict.status == "no_evidence"
    assert "1 claim linking" in text and "none gives a direction" in text
    assert "Found 1 forward edge, none usable (1 moderate, mediate or regulate it without a direction)." in searched


def test_categorical_cause_only(graph, make_ctx):
    # "zone type" [unchanged] associated_with total cover: a comparison of zones, no direction
    verdict, _, searched = run(edge_cands(graph, ["camo:edge_f06a4862f844"]), make_ctx())
    assert verdict.status == "no_evidence" and "compare categories of the cause" in searched


def test_prevented_change_only(graph, make_ctx):
    # "use of adaptable-mix seed mix prevents [unchanged] increase in community diversity"
    verdict, _, searched = run(edge_cands(graph, ["camo:edge_41a7453a63ad"]), make_ctx())
    assert verdict.status == "no_evidence" and "prevented a change" in searched


def test_answered_uses_baseline_wording(graph, make_ctx):
    ctx = make_ctx()
    c = edge_cands(graph, ["camo:edge_9ab77deefcdf"])
    votes = registry.get("interpreter", "sentence").interpret(c, ctx)
    verdict = registry.get("aggregator", "studies").aggregate(votes, c, ctx)
    assert verdict.status == "answered"
    assert registry.get("renderer", "searched").render(verdict, c, "low", ctx) == registry.get(
        "renderer", "baseline"
    ).render(verdict, c, "low", ctx)


def test_null_finding_is_answered_not_no_evidence(graph, make_ctx):
    # "k was lower, but not significantly different": a tested null is an answer (no_effect), not a gap
    verdict, _, searched = run(edge_cands(graph, ["camo:edge_20171069c1db"]), make_ctx())
    assert verdict.status == "answered" and verdict.direction == "no_effect" and searched is None


def test_unparsed_question_says_no_search_ran(make_ctx):
    q = Question("q", "Which seed-mix species persist in each ecosite type?")
    c = Candidates(Frame(ParsedQuestion(q, None, None, False), Side(None), Side(None), "none", 0.0), {}, {})
    verdict, text, searched = run(c, make_ctx())
    assert verdict.status == "no_evidence" and searched.startswith("no edge search was run")
