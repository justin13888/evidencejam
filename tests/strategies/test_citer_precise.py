"""precise citer: direction filter, twin dedupe, ordering, cap, fallback. Real edge ids from the graph."""

from __future__ import annotations

from collections import defaultdict

import pytest

from camoreasoning import registry
from camoreasoning.contracts import EdgeVote, Verdict
from camoreasoning.strategies.citer.precise import CAP


@pytest.fixture(scope="module")
def edges(graph):
    """twins: 3+ edges sharing (document, original_sentence), graph order. singles: one-edge sentences in
    other documents, each from a distinct document."""
    by: dict[tuple, list[str]] = defaultdict(list)
    for eid, e in graph.edges.items():
        if e.get("original_sentence"):
            by[(e["source_document"], e["original_sentence"])].append(eid)
    twins = next(v for v in by.values() if len(v) >= 3)
    tdoc = graph.edges[twins[0]]["source_document"]
    singles, docs = [], {tdoc}
    for (doc, _), ids in by.items():
        if len(ids) == 1 and doc not in docs:
            singles.append(ids[0])
            docs.add(doc)
        if len(singles) == 40:
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


def test_registered_and_no_llm(make_ctx, graph, edges):
    ctx = make_ctx()
    _, s = edges
    v = Verdict("answered", "increase", (vote(graph, s[0], 1),))
    assert cite(v, ctx) == [s[0]] and ctx.llm.meter.calls == 0


def test_no_evidence_is_empty(make_ctx, graph, edges):
    _, s = edges
    v = Verdict("no_evidence", None, (vote(graph, s[0], 1, included=False),))
    assert cite(v, make_ctx()) == []
    assert cite(Verdict("no_evidence", None, ()), make_ctx()) == []


@pytest.mark.parametrize("direction,effect", [("increase", 1), ("decrease", -1), ("no_effect", 0)])
def test_direction_filter(make_ctx, graph, edges, direction, effect):
    _, s = edges
    votes = (vote(graph, s[0], 1), vote(graph, s[1], -1), vote(graph, s[2], 0), vote(graph, s[3], None),
             vote(graph, s[4], effect, included=False))  # fmt: skip
    v = Verdict("answered", direction, votes)
    ids = cite(v, make_ctx())
    assert ids == [s[[1, -1, 0].index(effect)]]
    check(ids, v)


@pytest.mark.parametrize("direction", ["mixed", "unclear"])
def test_mixed_keeps_both_signs(make_ctx, graph, edges, direction):
    _, s = edges
    votes = (vote(graph, s[0], 1), vote(graph, s[1], -1), vote(graph, s[2], 0), vote(graph, s[3], None),
             vote(graph, s[4], 1, included=False))  # fmt: skip
    v = Verdict("answered", direction, votes)
    ids = cite(v, make_ctx())
    assert ids == s[:3]
    check(ids, v)


def test_twins_same_effect_collapse_to_first_in_graph_order(make_ctx, graph, edges):
    t, s = edges
    # votes listed in reverse graph order: the earliest graph edge still wins
    votes = (vote(graph, t[2], 1), vote(graph, t[1], 1), vote(graph, t[0], 1), vote(graph, s[0], 1))
    v = Verdict("answered", "increase", votes)
    ids = cite(v, make_ctx())
    assert t[0] in ids and t[1] not in ids and t[2] not in ids and s[0] in ids
    check(ids, v)


def test_twins_different_effect_both_kept(make_ctx, graph, edges):
    t, _ = edges
    votes = (vote(graph, t[0], 1), vote(graph, t[1], -1), vote(graph, t[2], 1))
    v = Verdict("answered", "mixed", votes)
    ids = cite(v, make_ctx())
    assert ids == [t[0], t[1]]
    check(ids, v)


def test_twin_excluded_by_direction_does_not_block_sibling(make_ctx, graph, edges):
    t, _ = edges
    votes = (vote(graph, t[0], 0), vote(graph, t[1], 1))
    assert cite(Verdict("answered", "increase", votes), make_ctx()) == [t[1]]


def test_order_doc_then_grade_then_vote_order(make_ctx, graph, edges):
    t, s = edges
    votes = (
        vote(graph, s[0], 1, grade="very_low"),
        vote(graph, s[1], 1, grade="low"),
        vote(graph, s[0], 1),  # duplicate vote for the same edge
    )
    # same-doc ordering: use twins with different effects so all stay, under "mixed"
    tv = (
        vote(graph, t[0], 1, grade="very_low"),
        vote(graph, t[1], -1, grade="moderate"),
        vote(graph, t[2], 0, grade="low"),
    )
    v = Verdict("answered", "mixed", votes[:2] + tv + votes[2:])
    ids = cite(v, make_ctx())
    assert ids == [s[0], s[1], t[1], t[2], t[0]]
    check(ids, v)


def test_same_grade_keeps_vote_order(make_ctx, graph, edges):
    t, _ = edges
    tv = (vote(graph, t[2], 0, grade="low"), vote(graph, t[0], 1, grade="low"), vote(graph, t[1], -1, grade="low"))
    assert cite(Verdict("answered", "mixed", tv), make_ctx()) == [t[2], t[0], t[1]]


def test_cap(make_ctx, graph, edges):
    _, s = edges
    v = Verdict("answered", "increase", tuple(vote(graph, e, 1) for e in s))
    ids = cite(v, make_ctx())
    assert ids == s[:CAP]
    check(ids, v)


def test_fallback_when_filter_leaves_nothing(make_ctx, graph, edges):
    _, s = edges
    votes = (
        vote(graph, s[0], -1),
        vote(graph, s[1], None),
        vote(graph, s[0], -1),
        vote(graph, s[2], 1, included=False),
    )
    v = Verdict("answered", "increase", votes)
    ids = cite(v, make_ctx())
    assert ids == [s[0], s[1]]
    check(ids, v)


def test_never_cites_non_included(make_ctx, graph, edges):
    t, s = edges
    votes = tuple(vote(graph, e, 1, included=False) for e in (*t, *s[:5])) + (vote(graph, s[5], 1),)
    for d in ("increase", "mixed", "unclear", "decrease"):
        v = Verdict("answered", d, votes)
        ids = cite(v, make_ctx())
        assert ids == [s[5]]
        check(ids, v)
