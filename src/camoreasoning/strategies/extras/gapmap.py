"""Baseline evidence pages plus a gap map judges can read and navigate (ROADMAP item 17).

`gapmap.html` is the cause x outcome grid: rows are cause-side classes, columns outcome-side classes,
each sorted by how many studies they have. A cell shows the number of studies (source documents) with
at least one claim from a node labelled with the row class to a node labelled with the column class,
or "gap" when there is none. Every cell, gaps included, links to its entry in `gapcells.html`. That
entry gives a template question for the cell (what a user would ask, and what `ask.sh` takes) and
links to every question in this run that was linked to that cell, with the status it got. A question is
listed under every (cause class, outcome class) pair it linked to, so the listings show the C14 behaviour
(questions on a gap pair come back `no_evidence`) without the page promising it.

Shading only repeats the number in the cell (bands in `BANDS`), so no meaning depends on colour alone.
Static HTML, no script.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from html import escape
from pathlib import Path
from statistics import median

from camoreasoning.components import Context
from camoreasoning.contracts import Answer, Trace
from camoreasoning.registry import register
from camoreasoning.strategies.extras.baseline import HtmlExtras, _page, _rel, _slug
from camoreasoning.strategies.extras.limits import write_limits

MEMO = "extras.gapmap.run"
DENSEST = 15  # cells listed under "Where the graph is densest"
BANDS = (1, 2, 3, 6)  # lowest study count of shades 1-4; fixed so the legend can state them


def question_for(cause: str, outcome: str) -> str:
    return f"What effect does {cause} have on {outcome}?"


def studies(n: int) -> str:
    return f"{n} study" if n == 1 else f"{n} studies"


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


def band(n: int) -> int:
    """Shade 0 (gap), then 1 for 1 study, 2 for 2, 3 for 3 to 5, 4 for 6 or more."""
    return sum(n >= lo for lo in BANDS)


@register("extras", "gapmap")
class GapMapExtras(HtmlExtras):
    def write_run(self, answers: Sequence[Answer], traces: Sequence[Trace], ctx: Context) -> list[str]:
        ctx.memo[MEMO] = (list(answers), list(traces))
        paths = super().write_run(answers, traces, ctx)  # index.html + gapmap.html (via self.gap_map)
        if not ctx.taxonomy.empty:
            paths.append(_rel(self.cell_pages(ctx)))
        paths.append(write_limits(ctx))  # limits.html, from the recorded holdout report (item 20)
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
        head = "".join(f'<th scope="col"><span>{escape(o.label)}</span></th>' for o in outcomes)
        rows = []
        for c in causes:
            tds = []
            for o in outcomes:
                n = counts.get((c.id, o.id), 0)
                where = f"{escape(c.label)} on {escape(o.label)}"
                unit = "study" if n == 1 else "studies"
                text = f'{n}<span class="vh"> {unit}: {where}</span>' if n else f'gap<span class="vh">: {where}</span>'
                link = f'<a href="gapcells.html#{cell_id(c.id, o.id)}">{text}</a>'
                tds.append(f'<td class="d{band(n)}">{link}</td>')
            rows.append(f'<tr><th scope="row">{escape(c.label)}</th>{"".join(tds)}</tr>')
        dense = sorted((x for x in cells if x[2]), key=lambda x: -x[2])[:DENSEST]
        dense_li = "".join(
            f'<li><a href="gapcells.html#{cell_id(c.id, o.id)}">{escape(c.label)} on {escape(o.label)}</a>: '
            f"{studies(n)}</li>"
            for c, o, n in dense
        )
        empty_rows = [c.label for c in causes if not any(counts.get((c.id, o.id)) for o in outcomes)]
        body = (
            "<h1>Evidence gap map</h1>"
            "<p>Rows are interventions and conditions; columns are outcomes. Each cell counts the studies with "
            "at least one claim from the row to the column. <strong>gap</strong> means the graph has no such "
            "claim. Every cell links to an "
            'example question and to the questions in this run that asked about it (<a href="gapcells.html">'
            "all cells</a>). Darker shading repeats the count: 1 study, 2, 3 to 5, and 6 or more.</p>"
            '<p>Where answers go wrong, and what we do not try: <a href="limits.html">honest limits</a>.</p>'
            f"<ul><li>{len(causes)} interventions and conditions × {len(outcomes)} outcomes = {len(cells)} cells"
            f"</li><li>{len(filled)} cells have evidence; {len(cells) - len(filled)} are gaps "
            f"({(len(cells) - len(filled)) / max(1, len(cells)):.0%})</li>"
            f"<li>Studies per non-empty cell: median {median(filled) if filled else 0:g}, "
            f"most {max(filled, default=0)}</li>"
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
                found = studies(n) if n else "<strong>gap</strong>, no claim in the graph"
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
