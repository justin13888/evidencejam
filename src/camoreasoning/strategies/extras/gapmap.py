"""Baseline evidence pages plus a gap map judges can read and navigate (ROADMAP item 17).

`gapmap.html` is the cause x outcome grid: rows are cause-side classes, columns outcome-side classes,
each sorted by how many studies they have. A cell shows the number of studies (source documents) with
at least one claim from a node labelled with the row class to a node labelled with the column class,
or "gap" when there is none. Every cell, gaps included, links to its entry in `gapcells.html`. That
entry gives a template question for the cell (what a user would ask, and what `ask.sh` takes) and
links to every question in this run that was linked to that cell, with the status it got. A question
in a gap cell should come back `no_evidence`, so the map also shows the C14 behaviour.

Shading only repeats the number in the cell, so no meaning depends on colour alone.
Static HTML, no script.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from html import escape
from pathlib import Path

from camoreasoning.components import Context
from camoreasoning.contracts import Answer, Trace
from camoreasoning.registry import register
from camoreasoning.strategies.extras.baseline import HtmlExtras, _page, _rel, _slug

MEMO = "extras.gapmap.run"
DENSEST = 15  # cells listed under "Where the graph is densest"


def question_for(cause: str, outcome: str) -> str:
    return f"What effect does {cause} have on {outcome}?"


def cell_id(cause_id: str, outcome_id: str) -> str:
    return f"{cause_id}--{outcome_id}"


def study_counts(ctx: Context) -> dict[tuple[str, str], int]:
    """(cause class, outcome class) -> number of studies with a claim from the one to the other."""
    tax, docs = ctx.taxonomy, defaultdict(set)
    for e in ctx.graph.edges.values():
        for s in tax.classes_of(e["subject"]):
            for o in tax.classes_of(e["object"]):
                docs[(s.class_id, o.class_id)].add(e.get("source_document", ""))
    return {k: len(v) for k, v in docs.items()}


def band(n: int, cuts: tuple[int, ...]) -> int:
    """Shade 0 (gap) to 4 (densest quarter of non-empty cells)."""
    if not n:
        return 0
    return 1 + sum(n > c for c in cuts)


def quartiles(values: list[int]) -> tuple[int, ...]:
    v = sorted(values)
    if not v:
        return (0, 0, 0)
    return tuple(v[min(len(v) - 1, len(v) * q // 4)] for q in (1, 2, 3))


@register("extras", "gapmap")
class GapMapExtras(HtmlExtras):
    def write_run(self, answers: Sequence[Answer], traces: Sequence[Trace], ctx: Context) -> list[str]:
        ctx.memo[MEMO] = (list(answers), list(traces))
        paths = super().write_run(answers, traces, ctx)  # index.html + gapmap.html (via self.gap_map)
        if not ctx.taxonomy.empty:
            paths.append(_rel(self.cell_pages(ctx)))
        return paths

    def _axes(self, ctx: Context, counts: dict[tuple[str, str], int]):
        causes, outcomes = ctx.taxonomy.of_kind("cause"), ctx.taxonomy.of_kind("outcome")
        row_tot = {c.id: sum(counts.get((c.id, o.id), 0) for o in outcomes) for c in causes}
        col_tot = {o.id: sum(counts.get((c.id, o.id), 0) for c in causes) for o in outcomes}
        causes = sorted(causes, key=lambda c: (-row_tot[c.id], c.label))
        outcomes = sorted(outcomes, key=lambda o: (-col_tot[o.id], o.label))
        return causes, outcomes

    def gap_map(self, ctx: Context) -> Path:
        if ctx.taxonomy.empty:
            return super().gap_map(ctx)
        counts = study_counts(ctx)
        causes, outcomes = self._axes(ctx, counts)
        cells = [(c, o, counts.get((c.id, o.id), 0)) for c in causes for o in outcomes]
        filled = [n for _, _, n in cells if n]
        cuts = quartiles(filled)
        head = "".join(f'<th scope="col"><span>{escape(o.label)}</span></th>' for o in outcomes)
        rows = []
        for c in causes:
            tds = []
            for o in outcomes:
                n = counts.get((c.id, o.id), 0)
                where = f"{escape(c.label)} on {escape(o.label)}"
                text = f'{n}<span class="vh"> studies: {where}</span>' if n else f'gap<span class="vh">: {where}</span>'
                link = f'<a href="gapcells.html#{cell_id(c.id, o.id)}">{text}</a>'
                tds.append(f'<td class="d{band(n, cuts)}">{link}</td>')
            rows.append(f'<tr><th scope="row">{escape(c.label)}</th>{"".join(tds)}</tr>')
        dense = sorted((x for x in cells if x[2]), key=lambda x: -x[2])[:DENSEST]
        dense_li = "".join(
            f'<li><a href="gapcells.html#{cell_id(c.id, o.id)}">{escape(c.label)} on {escape(o.label)}</a>: '
            f"{n} studies</li>"
            for c, o, n in dense
        )
        empty_rows = [c.label for c in causes if not any(counts.get((c.id, o.id)) for o in outcomes)]
        body = (
            "<h1>Evidence gap map</h1>"
            "<p>Rows are interventions and conditions; columns are outcomes. Each cell counts the studies with "
            "at least one claim from the row to the column. <strong>gap</strong> means the graph has no such "
            "claim, so a question about that pair is answered <em>no evidence</em>. Every cell links to an "
            'example question and to the questions in this run that asked about it (<a href="gapcells.html">'
            "all cells</a>). Darker shading repeats the count: the densest quarter of non-empty cells is "
            "darkest.</p>"
            f"<ul><li>{len(causes)} interventions and conditions × {len(outcomes)} outcomes = {len(cells)} cells"
            f"</li><li>{len(filled)} cells have evidence; {len(cells) - len(filled)} are gaps "
            f"({(len(cells) - len(filled)) / len(cells):.0%})</li>"
            f"<li>Studies per non-empty cell: median {cuts[1]}, most {max(filled, default=0)}</li>"
            + (f"<li>No evidence for any outcome: {escape(', '.join(empty_rows))}</li>" if empty_rows else "")
            + "</ul>"
            f"<h2>Where the graph is densest</h2><ol>{dense_li}</ol>"
            '<h2>The grid</h2><div class="wrap"><table class="gapmap">'
            "<caption>Studies per intervention or condition (rows) and outcome (columns)</caption>"
            f'<thead><tr><th scope="col">Intervention or condition</th>{head}</tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
        return _page(ctx, "gapmap.html", "Evidence gap map", body)

    def cell_pages(self, ctx: Context) -> Path:
        counts = study_counts(ctx)
        causes, outcomes = self._axes(ctx, counts)
        answers, traces = ctx.memo.get(MEMO, ([], []))
        asked: dict[tuple[str, str], list[tuple[Answer, Trace]]] = defaultdict(list)
        for a, t in zip(answers, traces):
            f = t.frame
            if f is None:
                continue
            for c in f.cause.classes:
                for o in f.outcome.classes:
                    asked[(c.id, o.id)].append((a, t))
        sections = []
        for c in causes:
            items = []
            for o in outcomes:
                n = counts.get((c.id, o.id), 0)
                unit = "study" if n == 1 else "studies"
                found = f"{n} {unit}" if n else "<strong>gap</strong>, no claim in the graph"
                runs = "".join(
                    f'<li><a href="{_slug(a.id)}.html">{escape(a.id)}</a>: {escape(t.question.text)} '
                    f"({escape(a.status.replace('_', ' '))})</li>"
                    for a, t in asked.get((c.id, o.id), [])
                )
                items.append(
                    f'<li id="{cell_id(c.id, o.id)}"><strong>{escape(o.label)}</strong>: '
                    + found
                    + f". Example question: <q>{escape(question_for(c.label, o.label))}</q>"
                    + (f"<ul>{runs}</ul>" if runs else "")
                    + "</li>"
                )
            head = f'<h2 id="{escape(c.id)}">{escape(c.label)}</h2>'
            sections.append(f"<section>{head}<ul>{''.join(items)}</ul></section>")
        body = (
            '<h1>Gap map cells</h1><p><a href="gapmap.html">Back to the gap map</a>. One section per intervention '
            "or condition; each outcome gives the study count or <strong>gap</strong>, an example question, and "
            "the questions from this run linked to that pair, with the status each got.</p>" + "".join(sections)
        )
        return _page(ctx, "gapcells.html", "Gap map cells", body)
