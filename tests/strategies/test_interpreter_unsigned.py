"""#76: the `unsigned` interpreter reads an edge that names no direction as an unsigned vote."""

from __future__ import annotations

import pytest

from camoreasoning import registry
from camoreasoning.contracts import Candidates, Frame, ParsedQuestion, Question, Side
from camoreasoning.strategies.interpreter import sentence, unsigned


def read(graph, eid: str, module=unsigned):
    e = graph.edges[eid]
    return module.read_edge(e, graph.nodes[e["object"]], 1, 1, graph.nodes[e["subject"]])


@pytest.mark.parametrize(
    "eid",
    ["camo:edge_fd4d9a5c40f7",  # rule 1: "Increased concentration of nitrate" with itself
     "camo:edge_2d54f5d7e7ce",  # rule 2: -> "Shifted ectomycorrhizal fungal community composition" [None]
     "camo:edge_948b5fdf1f56"],  # rule 3: "Seeding method was associated with native cover in Valley plots"
)  # fmt: skip
def test_an_association_with_no_direction_is_unsigned(graph, eid):
    assert read(graph, eid, sentence)[2] == "associational"
    assert read(graph, eid) == (None, True, "unsigned_association")


@pytest.mark.parametrize(
    "eid",
    ["camo:edge_0db71e166028",  # "a statistically significant increase in ... sapling number ... with forest age"
     "camo:edge_bbf6b0c9753f",  # "positively related to total macroinvertebrate abundance"
     "camo:edge_2897c7463129"],  # "lower on reclaimed mine lands compared to the REF area"
)  # fmt: skip
def test_an_association_that_says_which_way_is_read_as_sentence_reads_it(graph, eid):
    assert read(graph, eid) == read(graph, eid, sentence)
    assert read(graph, eid)[0] in (1, -1)


def test_an_unsigned_difference_stays_as_sentence_reads_it(graph):
    """'Seeding method was associated with richness (F=112.04, P=0.000)', object [unchanged]: rule 3b."""
    assert read(graph, "camo:edge_c641160f3447") == read(graph, "camo:edge_c641160f3447", sentence)
    assert read(graph, "camo:edge_c641160f3447") == (None, False, "unsigned_difference")


def verdict(graph, ctx, eids):
    q = Question("q", "What effect does cause have on outcome?")
    frame = Frame(ParsedQuestion(q, "cause", "outcome", True), Side("cause"), Side("outcome"), "regex", 1.0)
    cands = Candidates(frame, {graph.edges[e]["subject"]: 1 for e in eids},
                       {graph.edges[e]["object"]: 1 for e in eids}, forward=tuple(eids))  # fmt: skip
    votes = registry.get("interpreter", "unsigned").interpret(cands, ctx)
    return registry.get("aggregator", "studies").aggregate(votes, cands, ctx)


def test_only_unsigned_evidence_is_unclear_not_no_evidence(graph, make_ctx):
    """D-Q0021's edge, gold unsigned: 'Seeding method was associated with native cover in Valley plots'."""
    v = verdict(graph, make_ctx(), ["camo:edge_948b5fdf1f56"])
    assert (v.status, v.direction) == ("answered", "unclear")


def test_an_unsigned_vote_never_outvotes_a_signed_one(graph, make_ctx):
    """Different studies, one unsigned and one signed: the signed study decides."""
    signed, unsigned_eid = "camo:edge_0db71e166028", "camo:edge_2d54f5d7e7ce"
    assert graph.edges[signed]["source_document"] != graph.edges[unsigned_eid]["source_document"]
    v = verdict(graph, make_ctx(), [signed, unsigned_eid])
    assert (v.status, v.direction) == ("answered", "increase")


def test_unsigned_is_the_default_interpreter():
    assert registry.get("interpreter").__class__ is unsigned.UnsignedInterpreter
