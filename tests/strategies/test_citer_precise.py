"""precise citer: every included edge, round-robin by study, strongest grade first. Real edge ids."""

from __future__ import annotations

from collections import defaultdict

import pytest

from camoreasoning import registry
from camoreasoning.contracts import EdgeVote, Verdict
from camoreasoning.strategies.citer.precise import CAP


@pytest.fixture(scope="module")
def edges(graph):
    """twins: 3+ edges sharing (document, original_sentence). singles: one edge each from distinct documents."""
    by: dict[tuple, list[str]] = defaultdict(list)
    for eid, e in graph.edges.items():
        if e.get("original_sentence"):
            by[(e["source_document"], e["original_sentence"])].append(eid)
    twins = next(v for v in by.values() if len(v) >= 3)
    docs, singles = {graph.edges[twins[0]]["source_document"]}, []
    for (doc, _), ids in by.items():
        if len(ids) == 1 and doc not in docs:
            singles.append(ids[0])
            docs.add(doc)
        if len(singles) == CAP + 5:
            break
    return twins, singles


def vote(graph, eid, effect, included=True, grade=None) -> EdgeVote:
    e = graph.edges[eid]
    return EdgeVote(eid, e["source_document"], effect, included, "test", grade or e.get("certainty_grade"))


def cite(verdict, ctx):
    return registry.get("citer", "precise").cite(verdict, ctx)


def check(ids, verdict):
    assert set(ids) <= {v.edge_id for v in verdict.included} and len(ids) == len(set(ids)) <= CAP
    assert bool(ids) == (verdict.status == "answered")


def test_no_evidence_is_empty(make_ctx, graph, edges):
    _, s = edges
    assert cite(Verdict("no_evidence", None, (vote(graph, s[0], 1, included=False),)), make_ctx()) == []


@pytest.mark.parametrize("direction", ["increase", "decrease", "no_effect", "mixed", "unclear"])
def test_cites_dissenting_and_null_votes(make_ctx, graph, edges, direction):
    """The answer rests on every included study, including the ones that disagree."""
    _, s = edges
    v = Verdict("answered", direction, (vote(graph, s[0], 1), vote(graph, s[1], -1), vote(graph, s[2], 0)))
    ids = cite(v, make_ctx())
    check(ids, v)
    assert set(ids) == set(s[:3])


def test_twins_all_cited(make_ctx, graph, edges):
    t, _ = edges
    v = Verdict("answered", "increase", tuple(vote(graph, e, 1) for e in t))
    assert cite(v, make_ctx()) == list(t)


def test_never_cites_non_included_and_no_duplicates(make_ctx, graph, edges):
    _, s = edges
    votes = (vote(graph, s[0], 1), vote(graph, s[0], 1), vote(graph, s[1], None, included=False))
    v = Verdict("answered", "increase", votes)
    ids = cite(v, make_ctx())
    check(ids, v)
    assert ids == [s[0]]


def test_round_robin_across_studies_strongest_first(make_ctx, graph, edges):
    t, s = edges
    # study A (twins): low, moderate, very_low; study B: one edge. Expect A's moderate, B, A's low, A's very_low.
    votes = (vote(graph, t[0], 1, grade="low"), vote(graph, t[1], 1, grade="moderate"),
             vote(graph, s[0], 1, grade="low"), vote(graph, t[2], 1, grade="very_low"))  # fmt: skip
    assert cite(Verdict("answered", "increase", votes), make_ctx()) == [t[1], s[0], t[0], t[2]]


def test_same_grade_keeps_vote_order(make_ctx, graph, edges):
    t, _ = edges
    votes = (vote(graph, t[2], 1, grade="low"), vote(graph, t[0], 1, grade="low"))
    assert cite(Verdict("answered", "increase", votes), make_ctx()) == [t[2], t[0]]


def test_cap_keeps_one_edge_per_study_first(make_ctx, graph, edges):
    _, s = edges
    assert len(s) > CAP
    v = Verdict("answered", "increase", tuple(vote(graph, e, 1) for e in s))
    ids = cite(v, make_ctx())
    check(ids, v)
    assert ids == s[:CAP]


def test_no_llm_calls(make_ctx, graph, edges):
    ctx = make_ctx()
    _, s = edges
    cite(Verdict("answered", "increase", (vote(graph, s[0], 1),)), ctx)
    assert ctx.llm.meter.calls == 0
