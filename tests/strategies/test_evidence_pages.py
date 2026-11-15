"""Item 16: every question page carries the answer card, per-study vote tables, the sign trace, and the
excluded and reversed edges, built from the Trace.

Renders the practice questions (questions.yaml, real taxonomy) and the fixture questions through the
whole pipeline, then reads each written page back and checks every section against the trace that
produced it. Row counts and quoted text are recomputed here from the trace and the graph.
"""

from __future__ import annotations

import dataclasses
import re
from collections import defaultdict
from html import escape

from camoreasoning.answers import load_questions
from camoreasoning.config import ROOT
from camoreasoning.contracts import Answer, Question, Trace, Verdict
from camoreasoning.pipeline import Pipeline, fallback_answer
from camoreasoning.registry import get
from camoreasoning.strategies import DEFAULTS
from camoreasoning.taxonomy import load_taxonomy

SECTIONS = ("answer", "studies", "sign-trace", "excluded", "reversed")
SECTION = re.compile(r'<section id="([^"]+)" aria-labelledby="\1-h"><h2 id="\1-h">[^<]+</h2>(.*?)</section>', re.S)
CARD = ["Status", "Direction", "Evidence certainty", "Our confidence"]


def rows(html: str) -> int:
    return html.count("<tr><td>")


def sections(page: str) -> dict[str, str]:
    found = SECTION.findall(page)
    assert [sid for sid, _ in found] == list(SECTIONS), [sid for sid, _ in found]
    return dict(found)


def check_page(ctx, answer: Answer, trace: Trace) -> dict[str, str]:
    """Every section is present and matches the trace; returns the section bodies."""
    assert answer.extras, answer.id
    page = (ROOT / answer.extras[0]).read_text(encoding="utf-8")
    assert '<html lang="en">' in page and "<script" not in page.lower()
    s = sections(page)
    g = ctx.graph

    # Answer card: direction, certainty and confidence are separate entries, each explained.
    card = s["answer"]
    dts = re.findall(r"<dt>([^<]+)</dt>", card)
    assert dts == CARD + (["Searched for"] if answer.searched_for else []), dts
    dds = dict(zip(dts, re.findall(r"<dd>(.*?)</dd>", card, re.S)))
    assert all('<span class="muted">(' in dd for dd in dds.values())
    assert dds["Our confidence"].startswith(f"{answer.confidence:.0%} ")
    if answer.direction:
        assert dds["Direction"].startswith(escape(answer.direction.replace("_", " ")) + " ")
    if answer.certainty:
        assert dds["Evidence certainty"].startswith(escape(answer.certainty.replace("_", " ")) + " ")
    assert escape(answer.answer) in card

    votes = trace.verdict.votes if trace.verdict else ()
    cand = trace.candidates
    reversed_ids = set(cand.reversed) if cand else set()

    # One vote table per study with a counted claim: quotes, comparators, DOI links, edge ids.
    by_doc = defaultdict(list)
    for v in votes:
        if v.included:
            by_doc[v.doc_id].append(v)
    studies = s["studies"]
    assert studies.count("<table>") == len(by_doc)
    tables = re.findall(r"<table>.*?</table>", studies, re.S)
    for table, (doc_id, vs) in zip(tables, by_doc.items()):
        doc = g.docs.get(doc_id, {})
        if doc.get("doi"):
            assert f'href="https://doi.org/{escape(doc["doi"])}"' in table
        assert "Study vote: <strong>" in table and rows(table) == len(vs)
        for v in vs:
            e = g.edges[v.edge_id]
            assert escape(v.edge_id) in table and escape(e.get("original_sentence", "")) in table
            for c in e.get("comparator") or []:
                if c.get("comparator_description"):
                    assert escape(c["comparator_description"]) in table
    if not by_doc:
        assert "None" in studies

    # Sign trace: one row per forward vote, with the rule that read it.
    forward = [v for v in votes if v.reason != "reversed" and v.edge_id not in reversed_ids and cand is not None]
    assert rows(s["sign-trace"]) == len(forward)
    for v in forward:
        assert escape(v.edge_id) in s["sign-trace"]
    if trace.verdict and trace.verdict.doc_effects:
        assert "Study votes: " in s["sign-trace"]

    # Excluded: forward votes not counted, then near misses.
    excluded = [v for v in votes if not v.included and v.reason != "reversed"]
    near = cand.near_miss if cand else ()
    assert rows(s["excluded"]) == len(excluded) + len(near)
    for eid in [v.edge_id for v in excluded] + list(near):
        assert escape(eid) in s["excluded"]
        assert escape(g.edges[eid].get("original_sentence", "")) in s["excluded"]

    # Reversed: every outcome -> cause candidate, never counted.
    assert rows(s["reversed"]) == len(reversed_ids)
    for eid in reversed_ids:
        assert escape(eid) in s["reversed"]
    for sid in ("excluded", "reversed"):
        if not rows(s[sid]):
            assert "<p>None.</p>" in s[sid]
    return s


def test_practice_question_pages(make_ctx):
    """Default strategies, real taxonomy: a page per practice question, every section checked."""
    ctx = make_ctx(tax=load_taxonomy())
    answers, traces = Pipeline(ctx).run(load_questions(ROOT / "questions.yaml"))
    assert DEFAULTS["extras"] == "gapmap"
    for a, t in zip(answers, traces):
        check_page(ctx, a, t)
    assert any(a.status == "answered" for a in answers), "a practice question should be answered"


def test_fixture_pages_fill_every_section(make_ctx, questions):
    """Fixture questions fill the vote, sign and excluded sections with rows, not only the empty case.

    No fixture question has an outcome -> cause edge or a near miss, so the reversed and near-miss
    rows are exercised by turning an answered trace around: its forward edges become reversed edges
    and near misses, read the way every interpreter reads a reversed edge (not counted).
    """
    ctx = make_ctx()
    answers, traces = Pipeline(ctx).run(questions)
    filled = defaultdict(int)
    for a, t in zip(answers, traces):
        for sid, body in check_page(ctx, a, t).items():
            filled[sid] += bool(rows(body))
    assert all(filled[sid] for sid in ("studies", "sign-trace", "excluded")), dict(filled)

    a, t = next((a, t) for a, t in zip(answers, traces) if a.status == "answered")
    fwd = t.candidates.forward
    cand = dataclasses.replace(t.candidates, forward=(), reversed=fwd, near_miss=fwd[:1])
    votes = tuple(dataclasses.replace(v, effect=None, included=False, reason="reversed") for v in t.verdict.votes)
    turned = dataclasses.replace(t, candidates=cand, verdict=Verdict("no_evidence", None, votes))
    a = dataclasses.replace(a, id=f"{a.id}-turned", status="no_evidence", direction=None, certainty=None)
    a.extras = get("extras", DEFAULTS["extras"]).write_question(a, turned, ctx)
    s = check_page(ctx, a, turned)
    assert rows(s["reversed"]) == len(fwd) and rows(s["excluded"]) == 1
    assert not rows(s["studies"]) and not rows(s["sign-trace"])


def test_failed_trace_page_keeps_every_section(make_ctx):
    """A trace that failed before search still gets the full outline, escaped, with the error shown."""
    ctx = make_ctx()
    q = Question("bad<id>", "What effect does <b>fire</b> have on biomass?")
    a, t = fallback_answer(q, "boom"), Trace(q, error="RuntimeError('<boom>')")
    a.extras = get("extras", DEFAULTS["extras"]).write_question(a, t, ctx)
    s = check_page(ctx, a, t)
    page = (ROOT / a.extras[0]).read_text(encoding="utf-8")
    assert "<b>" not in page and "&lt;b&gt;fire&lt;/b&gt;" in page
    assert "failed part-way" in s["answer"] and "&lt;boom&gt;" in s["answer"]
    assert all("None" in s[sid] for sid in ("studies", "sign-trace", "excluded", "reversed"))
