"""Contract suite for runtime stages, parametrized over EVERY registered strategy.

Each stage is fed baseline upstream outputs (with the fixture taxonomy and with an empty one) and
checked against the invariants in components.py. A new strategy passes here or it is not done.
"""

from __future__ import annotations

import inspect

import pytest

from camoreasoning import registry
from camoreasoning.components import BASES
from camoreasoning.contracts import Answer, Candidates, EdgeVote, Features, Frame, ParsedQuestion, Trace, Verdict
from camoreasoning.pipeline import features_of
from camoreasoning.schema import ANSWER_CERTAINTY, DIRECTIONS
from camoreasoning.signs import is_null_finding
from camoreasoning.taxonomy import Taxonomy


def names(stage):
    return registry.names(stage)


@pytest.fixture(params=["fixture_taxonomy", "empty_taxonomy"])
def ctx(request, make_ctx):
    return make_ctx(tax=None if request.param == "fixture_taxonomy" else Taxonomy())


def upstream(ctx, questions, until: str):
    """Baseline outputs up to (not including) `until`, per question."""
    b = {s: registry.get(s, "baseline") for s in BASES}
    parsed = [b["parser"].parse(q, ctx) for q in questions]
    if until == "linker":
        return parsed
    frames = b["linker"].link(parsed, ctx)
    if until == "retriever":
        return frames
    cands = [b["retriever"].retrieve(f, ctx) for f in frames]
    if until == "interpreter":
        return cands
    votes = [b["interpreter"].interpret(c, ctx) for c in cands]
    if until == "aggregator":
        return list(zip(votes, cands))
    return [(b["aggregator"].aggregate(v, c, ctx), c) for v, c in zip(votes, cands)]


def test_every_stage_has_baseline_and_strategies_subclass_their_stage():
    for stage, base in BASES.items():
        assert "baseline" in names(stage), stage
        for n in names(stage):
            cls = type(registry.get(stage, n))
            assert issubclass(cls, base) and not inspect.isabstract(cls), (stage, n)


@pytest.mark.parametrize("name", names("parser"))
def test_parser(name, ctx, questions):
    p = registry.get("parser", name)
    for q in questions:
        out = p.parse(q, ctx)
        assert isinstance(out, ParsedQuestion) and out.question == q
        assert out.cause_text is None or isinstance(out.cause_text, str)
    assert ctx.llm.meter.calls == 0
    hit = p.parse(questions[0], ctx)
    assert hit.template_hit and hit.cause_text and hit.outcome_text


@pytest.mark.parametrize("name", names("linker"))
def test_linker(name, ctx, questions):
    parsed = upstream(ctx, questions, "linker")
    frames = registry.get("linker", name).link(parsed, ctx)
    assert len(frames) == len(parsed)
    for p, f in zip(parsed, frames):
        assert isinstance(f, Frame) and f.parsed is p and isinstance(f.margin, float)
        for side in (f.cause, f.outcome):
            assert all(r.id in ctx.taxonomy.classes for r in side.classes)
            assert all(r.id in ctx.graph.nodes for r in side.nodes)
            assert all(r.polarity in (-1, 0, 1) for r in (*side.classes, *side.nodes))
    assert ctx.llm.meter.calls <= -(-len(parsed) // 25)


@pytest.mark.parametrize("name", names("retriever"))
def test_retriever(name, ctx, questions):
    g = ctx.graph
    for f in upstream(ctx, questions, "retriever"):
        c = registry.get("retriever", name).retrieve(f, ctx)
        assert isinstance(c, Candidates) and c.frame is f
        assert not set(c.forward) & set(c.reversed)
        for e in c.forward:
            assert g.edges[e]["subject"] in c.cause_nodes and g.edges[e]["object"] in c.outcome_nodes
        for e in c.reversed:
            assert g.edges[e]["subject"] in c.outcome_nodes and g.edges[e]["object"] in c.cause_nodes
        assert all(e in g.edges for e in c.near_miss)
    assert ctx.llm.meter.calls == 0


@pytest.mark.parametrize("name", names("interpreter"))
def test_interpreter(name, ctx, questions):
    for c in upstream(ctx, questions, "interpreter"):
        votes = registry.get("interpreter", name).interpret(c, ctx)
        assert sorted(v.edge_id for v in votes) == sorted((*c.forward, *c.reversed))
        for v in votes:
            assert isinstance(v, EdgeVote) and v.effect in (-1, 0, 1, None)
            assert v.doc_id == ctx.graph.edges[v.edge_id].get("source_document", "")
            if v.edge_id in c.reversed:
                assert not v.included
            if v.included and is_null_finding(ctx.graph.edges[v.edge_id]):
                assert v.effect == 0
    assert ctx.llm.meter.calls == 0


@pytest.mark.parametrize("name", names("aggregator"))
def test_aggregator(name, ctx, questions):
    for votes, c in upstream(ctx, questions, "aggregator"):
        v = registry.get("aggregator", name).aggregate(votes, c, ctx)
        assert isinstance(v, Verdict) and 0 <= v.agreement <= 1
        assert (v.status == "no_evidence") == (not any(x.included for x in votes))
        assert (v.direction is None) == (v.status == "no_evidence")
        assert v.direction is None or v.direction in DIRECTIONS


@pytest.mark.parametrize("name", names("grader"))
def test_grader(name, ctx, questions):
    for v, _ in upstream(ctx, questions, "grader"):
        g = registry.get("grader", name).grade(v, ctx)
        assert (g is None) == (v.status == "no_evidence")
        assert g is None or g in ANSWER_CERTAINTY


@pytest.mark.parametrize("name", names("calibrator"))
def test_calibrator(name, ctx, questions):
    cal = registry.get("calibrator", name)
    for v, c in upstream(ctx, questions, "calibrator"):
        f = features_of(c.frame, c, v, None if v.status == "no_evidence" else "low")
        assert isinstance(f, Features)
        x = cal.confidence(f, ctx)
        assert 0.0 <= x <= 1.0 and x == cal.confidence(f, ctx)


@pytest.mark.parametrize("name", names("citer"))
def test_citer(name, ctx, questions):
    for v, _ in upstream(ctx, questions, "citer"):
        ids = registry.get("citer", name).cite(v, ctx)
        assert set(ids) <= {x.edge_id for x in v.included} and len(ids) == len(set(ids))
        assert bool(ids) == (v.status == "answered")


@pytest.mark.parametrize("name", names("renderer"))
def test_renderer(name, ctx, questions):
    for v, c in upstream(ctx, questions, "renderer"):
        text, searched = registry.get("renderer", name).render(v, c, None if v.status == "no_evidence" else "low", ctx)
        assert isinstance(text, str) and text.strip()
        assert bool(searched and searched.strip()) == (v.status == "no_evidence")
    assert ctx.llm.meter.calls == 0


@pytest.mark.parametrize("name", names("extras"))
def test_extras(name, ctx, questions):
    from camoreasoning.config import ROOT

    w = registry.get("extras", name)
    answers, traces = [], []
    for v, c in upstream(ctx, questions, "extras")[:12]:
        a = Answer(c.frame.parsed.question.id, v.status, "x", 0.5, v.direction)
        t = Trace(c.frame.parsed.question, c.frame, c, v)
        for p in w.write_question(a, t, ctx):
            html = (ROOT / p).read_text(encoding="utf-8")
            assert '<html lang="' in html and "<title>" in html and "<script" not in html.lower()
        answers.append(a)
        traces.append(t)
    w.write_run(answers, traces, ctx)
    w.write_question(answers[0], Trace(traces[0].question, error="boom"), ctx)  # partial trace must not raise
