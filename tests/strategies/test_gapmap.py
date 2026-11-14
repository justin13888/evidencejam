"""Item 17: the gap map renders, its counts are right, every link resolves, and gap cells answer no_evidence.

Runs the whole pipeline on the fixture taxonomy, then reads the written HTML back. Study counts are
recomputed here from the graph, not taken from `gapmap.study_counts`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from html import unescape

import pytest

from camoreasoning.config import ROOT
from camoreasoning.pipeline import Pipeline
from camoreasoning.registry import get
from camoreasoning.taxonomy import Taxonomy

CELL = re.compile(r'<td class="d(\d)"><a href="gapcells\.html#([^"]+)">(.*?)</a></td>')
ENTRY = re.compile(r'<li id="([^"]+)"><strong>.*?</strong>: (.*?)\. Example question: <q>.*?</q>(<ul>.*?</ul>)?</li>')


@pytest.fixture
def written(make_ctx, questions):
    ctx = make_ctx()
    answers, traces = Pipeline(ctx).run(questions)
    paths = get("extras", "gapmap").write_run(answers, traces, ctx)
    return ctx, answers, paths


def expected_counts(ctx) -> dict[tuple[str, str], int]:
    docs = defaultdict(set)
    for e in ctx.graph.edges.values():
        for s in ctx.taxonomy.classes_of(e["subject"]):
            for o in ctx.taxonomy.classes_of(e["object"]):
                docs[(s.class_id, o.class_id)].add(e.get("source_document", ""))
    return {k: len(v) for k, v in docs.items()}


def test_gapmap_is_the_default():
    from camoreasoning.strategies import DEFAULTS

    assert DEFAULTS["extras"] == "gapmap"


def test_grid_counts_and_labels(written):
    ctx, _, paths = written
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["index.html", "gapmap.html", "gapcells.html"]
    assert all((ROOT / p).exists() for p in paths)
    html = (ctx.out_dir / "gapmap.html").read_text(encoding="utf-8")
    assert "<script" not in html.lower()
    causes, outcomes = ctx.taxonomy.of_kind("cause"), ctx.taxonomy.of_kind("outcome")
    cells = CELL.findall(html)
    assert len(cells) == len(causes) * len(outcomes)
    counts, labels = expected_counts(ctx), {c.id: c.label for c in ctx.taxonomy.classes.values()}
    seen = set()
    for band, anchor, text in cells:
        c, o = anchor.split("--")
        n, where = counts.get((c, o), 0), f"{labels[c]} on {labels[o]}"
        seen.add((c, o))
        hidden = unescape(re.search(r'<span class="vh">(.*?)</span>', text).group(1))
        if n:
            unit = "study" if n == 1 else "studies"
            assert text.startswith(f"{n}<") and hidden == f" {unit}: {where}" and band != "0", (anchor, text)
        else:
            assert text.startswith("gap<") and hidden == f": {where}" and band == "0", (anchor, text)
    assert seen == {(c.id, o.id) for c in causes for o in outcomes}
    bands = {b for b, _, _ in cells}
    assert "0" in bands and bands - {"0"}, "fixture should have both gaps and evidence"
    gaps = sum(b == "0" for b, _, _ in cells)
    assert f"{gaps} are gaps ({gaps / len(cells):.0%})" in html


def test_every_link_resolves(written):
    ctx, _, _ = written
    grid = (ctx.out_dir / "gapmap.html").read_text(encoding="utf-8")
    cells = (ctx.out_dir / "gapcells.html").read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', cells)
    assert len(ids) == len(set(ids))
    assert {a for _, a, _ in CELL.findall(grid)} <= set(ids)
    assert set(re.findall(r'href="gapcells\.html#([^"]+)"', grid)) <= set(ids)
    pages = set(re.findall(r'<a href="([^"#/]+\.html)"', cells))
    assert pages and all((ctx.out_dir / p).exists() for p in pages)


def test_questions_in_gap_cells_are_no_evidence(written):
    """C14 behaviour: a question listed under a gap cell must not come back answered."""
    ctx, answers, _ = written
    status = {a.id: a.status for a in answers}
    listed = gap_listed = 0
    for _, found, runs in ENTRY.findall((ctx.out_dir / "gapcells.html").read_text(encoding="utf-8")):
        for qid in re.findall(r'<a href="[^"]+\.html">([^<]+)</a>', runs or ""):
            listed += 1
            if found.startswith("<strong>gap"):
                gap_listed += 1
                assert status[unescape(qid)] == "no_evidence", qid
    assert listed and gap_listed, "fixture questions should land in both kinds of cell"


def test_empty_taxonomy_falls_back(make_ctx):
    ctx = make_ctx(tax=Taxonomy({}, (), "empty"))
    paths = get("extras", "gapmap").write_run([], [], ctx)
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["index.html", "gapmap.html"]
    assert "Available once taxonomy/classes.yaml is built" in (ctx.out_dir / "gapmap.html").read_text(encoding="utf-8")
