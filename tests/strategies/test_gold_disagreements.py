"""Item 10: gold audit disagreements as trap tests (experiments/gold/README.md, round 2).

The round-2 audit disagreed with the labeller on 3 of 40 items. Each became a correction in the gold, and
each is a reading a model (labeller or engine) can get wrong. Same engine chain as test_traps.py, at node
level, with the polarity a node label would give each cause node relative to the question's cause.
"""

from __future__ import annotations

import pytest

from camoreasoning import registry
from camoreasoning.contracts import Frame, ParsedQuestion, Question, Ref, Side
from tests.strategies.test_traps import ENGINE


def run(ctx, causes: dict[str, int], outcomes: dict[str, int]):
    """Ask at node level: {node_id: polarity relative to the question side}."""
    s = {st: registry.get(st, n) for st, n in ENGINE.items()}
    q = Question("gold", "What effect does cause have on outcome?")
    frame = Frame(ParsedQuestion(q, "cause", "outcome", True),
                  Side("cause", nodes=tuple(Ref(n, p) for n, p in causes.items())),
                  Side("outcome", nodes=tuple(Ref(n, p) for n, p in outcomes.items())), "regex", 1.0)  # fmt: skip
    cands = s["retriever"].retrieve(frame, ctx)
    verdict = s["aggregator"].aggregate(s["interpreter"].interpret(cands, ctx), cands, ctx)
    return verdict, s["grader"].grade(verdict, ctx)


def effect(verdict, edge_id: str):
    return next(v.effect for v in verdict.votes if v.edge_id == edge_id and v.included)


@pytest.fixture
def ctx(make_ctx):
    return make_ctx()


def test_decreased_share_of_fruiting_plants_is_a_fruiting_decrease(graph, ctx):
    """D-Q0003 "time period -> fruiting potential". The labeller dropped e2 as a different outcome. The
    audit kept it: "about 73% ... produced fruit ... only 18%" is a fall in fruiting (-1). With the same
    study's "remained steady" edge (0), the study ties, so the gold is mixed."""
    steady, fell = "camo:edge_15a7f5a2b502", "camo:edge_3cbccac46759"
    ends = {e: (graph.edges[e]["subject"], graph.edges[e]["object"]) for e in (steady, fell)}
    verdict, certainty = run(ctx, {ends[steady][0]: 1}, {ends[steady][1]: 1, ends[fell][1]: -1})
    assert effect(verdict, fell) == -1 and effect(verdict, steady) == 0
    assert verdict.direction == "mixed" and certainty == "low"


def test_deer_exclosure_is_deer_absence(graph, ctx):
    """D-Q0005 "deer presence -> adult tree density". Exclosures held more large trees, so deer presence
    lowers large-tree density (-1). The labeller dropped the edge; the audit kept it. With the same
    study's null on adult trees (0) the study ties: mixed."""
    null, exclosure = "camo:edge_f4cb3c80e187", "camo:edge_18caf0511a4d"
    deer, adults = graph.edges[null]["subject"], graph.edges[null]["object"]
    excl, dens = graph.edges[exclosure]["subject"], graph.edges[exclosure]["object"]
    verdict, _ = run(ctx, {deer: 1, excl: -1}, {adults: 1, dens: 1})
    assert effect(verdict, exclosure) == -1 and effect(verdict, null) == 0
    assert verdict.direction == "mixed"


@pytest.mark.xfail(reason="interpreter signs associated_with through qualifiers even for a categorical outcome; "
                          "gold (D2) says no usable sign -> unclear", strict=True)  # fmt: skip
def test_categorical_outcome_has_no_sign(graph, ctx):
    """D-Q0095 "vulnerability ranking -> flowering phenology". "Positively associated with ephemeral
    flowering" picks a category, not a quantity that rises or falls, so the edge carries no sign and the
    gold is unclear. The labeller signed it +1 (increase)."""
    e = "camo:edge_41b89878909d"
    verdict, _ = run(ctx, {graph.edges[e]["subject"]: 1}, {graph.edges[e]["object"]: 1})
    assert verdict.direction == "unclear"
