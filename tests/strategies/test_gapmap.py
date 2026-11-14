"""Item 17: the gap map renders, its counts are right, every link resolves, and gap pairs answer no_evidence.

Runs the whole pipeline on the fixture taxonomy, then reads the written HTML back. Study counts are
recomputed here from the graph, not taken from `gapmap.study_counts`.
"""

from __future__ import annotations

import dataclasses
import re
from collections import defaultdict
from html import escape, unescape
from statistics import median

import pytest

from camoreasoning.config import ROOT
from camoreasoning.contracts import Answer, Frame, ParsedQuestion, Question, Ref, Side, Trace
from camoreasoning.pipeline import Pipeline
from camoreasoning.registry import get
from camoreasoning.taxonomy import TaxonClass, Taxonomy

CELL = re.compile(r'<td class="d(\d)"><a href="gapcells\.html#([^"]+)">(.*?)</a></td>', re.S)
ENTRY = re.compile(
    r'<li id="([^"]+)"><strong>.*?</strong>: (.*?)\. Example question: <q>.*?</q>(<ul>.*?</ul>)?</li>', re.S
)


def write(ctx, questions):
    answers, traces = Pipeline(ctx).run(questions)
    return answers, traces, get("extras", "gapmap").write_run(answers, traces, ctx)


@pytest.fixture
def written(make_ctx, questions):
    ctx = make_ctx()
    answers, traces, paths = write(ctx, questions)
    return ctx, answers, traces, paths


def expected_counts(ctx) -> dict[tuple[str, str], int]:
    docs = defaultdict(set)
    for e in ctx.graph.edges.values():
        for s in ctx.taxonomy.classes_of(e["subject"]):
            for o in ctx.taxonomy.classes_of(e["object"]):
                docs[(s.class_id, o.class_id)].add(e.get("source_document", ""))
    return {k: len(v) for k, v in docs.items()}


def expected_band(n: int) -> str:
    return "0" if n == 0 else "1" if n == 1 else "2" if n == 2 else "3" if n <= 5 else "4"


def check_grid(ctx) -> list[tuple[str, str, int]]:
    """Every cell's count, shade, visible text and screen-reader label; returns (cause, outcome, n)."""
    html = (ctx.out_dir / "gapmap.html").read_text(encoding="utf-8")
    assert "<script" not in html.lower()
    causes, outcomes = ctx.taxonomy.of_kind("cause"), ctx.taxonomy.of_kind("outcome")
    counts, labels = expected_counts(ctx), {c.id: c.label for c in ctx.taxonomy.classes.values()}
    cells = CELL.findall(html)
    assert len(cells) == len(causes) * len(outcomes)
    out = []
    for band, anchor, text in cells:
        c, o = anchor.split("--")
        n = counts.get((c, o), 0)
        where = f"{escape(labels[c])} on {escape(labels[o])}"  # raw HTML: labels must arrive escaped
        assert band == expected_band(n), (anchor, n, band)
        if n:
            unit = "study" if n == 1 else "studies"
            assert text == f'{n}<span class="vh"> {unit}: {where}</span>', text
        else:
            assert text == f'gap<span class="vh">: {where}</span>', text
        out.append((c, o, n))
    assert {(c, o) for c, o, _ in out} == {(c.id, o.id) for c in causes for o in outcomes}
    return out


def test_gapmap_is_the_default():
    from camoreasoning.strategies import DEFAULTS

    assert DEFAULTS["extras"] == "gapmap"


def test_grid_counts_labels_and_summary(written):
    ctx, _, _, paths = written
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["index.html", "gapmap.html", "gapcells.html"]
    assert all((ROOT / p).exists() for p in paths)
    cells = check_grid(ctx)
    filled = [n for _, _, n in cells if n]
    assert filled and len(filled) < len(cells), "fixture should have both gaps and evidence"
    html = (ctx.out_dir / "gapmap.html").read_text(encoding="utf-8")
    gaps = len(cells) - len(filled)
    assert f"{len(filled)} cells have evidence; {gaps} are gaps ({gaps / len(cells):.0%})" in html
    assert f"median {median(filled):g}, most {max(filled)}<" in html
    assert "&amp;" in html and "Mulch & surface" not in html, "the fixture's '&' label must be escaped"
    labels = {c.id: c.label for c in ctx.taxonomy.classes.values()}
    dense = re.findall(r"<li><a href=\"gapcells\.html#([^\"]+)\">[^<]*</a>: (\d+) (study|studies)</li>", html)
    assert [int(n) for _, n, _ in dense] == sorted(filled, reverse=True)[:15]
    assert all(unit == ("study" if n == "1" else "studies") for _, n, unit in dense)
    assert any(n == "1" for _, n, _ in dense), "fixture should have a 1-study cell among the densest"
    rowless = sorted(labels[c] for c in {c for c, _, _ in cells} if not any(n for cc, _, n in cells if cc == c))
    listed = re.search(r"<li>No evidence for any outcome: ([^<]*)</li>", html)
    assert sorted(unescape(listed.group(1)).split(", ")) == rowless if rowless else listed is None


def test_both_kind_class_is_a_row_and_a_column(make_ctx, taxonomy, questions):
    first_cause = taxonomy.of_kind("cause")[0]
    both = dataclasses.replace(first_cause, kind="both")
    tax = Taxonomy({**taxonomy.classes, both.id: both}, taxonomy.labels, taxonomy.version)
    ctx = make_ctx(tax=tax)
    write(ctx, questions[:5])
    cells = check_grid(ctx)
    assert any(c == both.id for c, _, _ in cells) and any(o == both.id for _, o, _ in cells)


def test_cause_with_no_evidence_is_listed(make_ctx, taxonomy):
    orphan = TaxonClass("orphan_cause", "cause", "Orphan <cause>")
    lonely = TaxonClass("orphan_outcome", "outcome", "Orphan outcome")  # gives every non-empty row a gap too
    classes = {**taxonomy.classes, orphan.id: orphan, lonely.id: lonely}
    ctx = make_ctx(tax=Taxonomy(classes, taxonomy.labels, taxonomy.version))
    get("extras", "gapmap").write_run([], [], ctx)
    html = (ctx.out_dir / "gapmap.html").read_text(encoding="utf-8")
    listed = re.search(r"<li>No evidence for any outcome: ([^<]*)</li>", html)
    assert listed and listed.group(1) == "Orphan &lt;cause&gt;, Prescribed fire"  # both rows are all gaps
    assert sum(n == 0 for c, _, n in check_grid(ctx) if c == orphan.id) == len(taxonomy.of_kind("outcome")) + 1


def test_multi_class_question_is_listed_under_every_pair(make_ctx, taxonomy):
    (c1, c2), (o1, o2) = taxonomy.of_kind("cause")[:2], taxonomy.of_kind("outcome")[:2]
    q = Question("MULTI", "What effect does a & b have on <x>?")
    frame = Frame(ParsedQuestion(q, "a & b", "<x>", True),
                  Side("a & b", classes=(Ref(c1.id), Ref(c2.id))), Side("<x>", classes=(Ref(o1.id), Ref(o2.id))),
                  "regex", 1.0)  # fmt: skip
    ctx = make_ctx()
    get("extras", "gapmap").write_run([Answer("MULTI", "no_evidence", "x", 0.5)], [Trace(q, frame)], ctx)
    html = (ctx.out_dir / "gapcells.html").read_text(encoding="utf-8")
    cells = {cell for cell, _, runs in ENTRY.findall(html) if 'href="MULTI.html"' in (runs or "")}
    assert cells == {f"{c.id}--{o.id}" for c in (c1, c2) for o in (o1, o2)}
    assert "a &amp; b have on &lt;x&gt;? (no evidence)" in html and "<x>" not in html


def test_every_link_resolves(written):
    ctx, _, _, _ = written
    grid = (ctx.out_dir / "gapmap.html").read_text(encoding="utf-8")
    cells = (ctx.out_dir / "gapcells.html").read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', cells)
    assert len(ids) == len(set(ids))
    assert set(re.findall(r'href="gapcells\.html#([^"]+)"', grid)) <= set(ids)
    pages = set(re.findall(r'<a href="([^"#/]+\.html)"', cells))
    assert pages and all((ctx.out_dir / p).exists() for p in pages)


def test_questions_are_listed_under_their_linked_pairs(written):
    """Each question appears under exactly the (cause class, outcome class) pairs its frame linked."""
    ctx, answers, traces, _ = written
    html = (ctx.out_dir / "gapcells.html").read_text(encoding="utf-8")
    shown = defaultdict(set)
    for cell, _, runs in ENTRY.findall(html):
        for qid in re.findall(r'<a href="[^"]+\.html">([^<]+)</a>', runs or ""):
            shown[unescape(qid)].add(cell)
    causes = {c.id for c in ctx.taxonomy.of_kind("cause")}
    outcomes = {o.id for o in ctx.taxonomy.of_kind("outcome")}
    for a, t in zip(answers, traces):
        f = t.frame
        want = set()
        if f is not None:
            want = {f"{c.id}--{o.id}" for c in f.cause.classes for o in f.outcome.classes
                    if c.id in causes and o.id in outcomes}  # fmt: skip
        assert shown.get(a.id, set()) == want, a.id
    assert shown, "fixture questions should be listed somewhere"


def test_single_pair_questions_on_a_gap_are_no_evidence(written):
    """C14 behaviour, measured where it is well defined: a question linked to exactly one cause class
    and one outcome class, and no extra nodes, whose pair is a gap, has nothing to answer from."""
    ctx, answers, traces, _ = written
    counts = expected_counts(ctx)
    single = gap = 0
    for a, t in zip(answers, traces):
        f = t.frame
        if f is None or len(f.cause.classes) != 1 or len(f.outcome.classes) != 1:
            continue
        if f.cause.nodes or f.outcome.nodes:
            continue
        single += 1
        if not counts.get((f.cause.classes[0].id, f.outcome.classes[0].id)):
            gap += 1
            assert a.status == "no_evidence", a.id
    assert single and gap, (single, gap)


def test_empty_taxonomy_falls_back(make_ctx):
    ctx = make_ctx(tax=Taxonomy({}, (), "empty"))
    paths = get("extras", "gapmap").write_run([], [], ctx)
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["index.html", "gapmap.html"]
    assert "Available once taxonomy/classes.yaml is built" in (ctx.out_dir / "gapmap.html").read_text(encoding="utf-8")


def test_ask_leaves_a_batch_runs_pages_alone(tmp_path):
    """`ask` (ask.sh) writes under outputs/ask/, so the judged run's index, gap map and pages survive it."""
    import inspect

    from camoreasoning.config import OUTPUTS_DIR, Settings
    from camoreasoning.pipeline import ASK_DIR, ask, ask_frame, run_file

    assert ASK_DIR == OUTPUTS_DIR / "ask"
    assert inspect.signature(ask_frame).parameters["out_dir"].default == ASK_DIR  # the CLI path uses this default
    assert inspect.signature(ask).parameters["out_dir"].default == ASK_DIR
    out = tmp_path / "outputs"
    run_file(ROOT / "questions.yaml", out / "answers.json", Settings())
    before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert {"index.html", "gapmap.html", "gapcells.html"} <= {p.name for p in before}
    ask("What effect does mulch have on invasive species abundance?", Settings(), out_dir=out / "ask")
    after = {p: p.read_bytes() for p in out.rglob("*") if p.is_file() and (out / "ask") not in p.parents}
    assert after == before
    assert {"ASK.html", "index.html", "gapmap.html", "gapcells.html"} <= {p.name for p in (out / "ask").iterdir()}
