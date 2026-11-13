"""Static, script-free evidence pages: one per question, an index, and an evidence gap map."""

from __future__ import annotations

import os
import re
import shutil
from collections import defaultdict
from collections.abc import Sequence
from html import escape
from pathlib import Path
from string import Template

from camoreasoning.components import Context, ExtrasWriter
from camoreasoning.config import PRODUCT_DIR, ROOT
from camoreasoning.contracts import Answer, Trace
from camoreasoning.registry import register

EFFECT = {1: "increase", -1: "decrease", 0: "no effect", None: "unsigned"}


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return os.path.relpath(path.resolve(), ROOT)


def _slug(qid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", qid)[:80] or "q"


def _page(ctx: Context, name: str, title: str, body: str) -> Path:
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    css = ctx.out_dir / "style.css"
    if not css.exists():
        shutil.copyfile(PRODUCT_DIR / "style.css", css)
    tpl = Template((PRODUCT_DIR / "page.html").read_text(encoding="utf-8"))
    path = ctx.out_dir / name
    path.write_text(tpl.substitute(title=escape(title), css="style.css", body=body), encoding="utf-8")
    return path


def _votes_table(ctx: Context, t: Trace) -> str:
    if not t.verdict or not t.verdict.votes:
        return "<p>No candidate edges.</p>"
    g, rows = ctx.graph, []
    for v in t.verdict.votes:
        e, doc = g.edges[v.edge_id], g.doc(v.edge_id)
        cite = escape(f"{(doc.get('authors') or ['?'])[0].split(',')[0]} {doc.get('year', '')}".strip())
        doi = doc.get("doi")
        src = f'<a href="https://doi.org/{escape(doi)}">{cite}</a>' if doi else cite
        rows.append(
            f"<tr><td>{escape(g.subject(v.edge_id).get('name', ''))} <em>{escape(e.get('predicate', ''))}</em> "
            f"{escape(g.object(v.edge_id).get('name', ''))}<blockquote>{escape(e.get('original_sentence', ''))}"
            f"</blockquote></td><td>{EFFECT[v.effect]}</td>"
            f"<td>{'yes' if v.included else 'no'} ({escape(v.reason)})</td>"
            f"<td>{escape(str(v.certainty_grade))}, {escape(str(v.causal_language))}</td><td>{src}<br>"
            f"<code>{escape(v.edge_id)}</code></td></tr>"
        )
    return (
        '<div class="wrap"><table><caption>Edges considered</caption><thead><tr><th scope="col">Claim and quote</th>'
        '<th scope="col">Effect on outcome</th><th scope="col">Counted</th><th scope="col">Certainty, language</th>'
        '<th scope="col">Source</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
    )


@register("extras", "baseline")
class HtmlExtras(ExtrasWriter):
    def write_question(self, answer: Answer, trace: Trace, ctx: Context) -> list[str]:
        fields = [("Status", answer.status), ("Direction", answer.direction), ("Evidence certainty", answer.certainty),
                  ("Our confidence", f"{answer.confidence:.0%}"), ("Searched for", answer.searched_for)]  # fmt: skip
        card = "".join(f"<dt>{k}</dt><dd>{escape(str(v))}</dd>" for k, v in fields if v is not None)
        body = (
            f"<h1>{escape(trace.question.text or answer.id)}</h1><p>{escape(answer.answer)}</p><dl>{card}</dl>"
            f"<h2>Evidence</h2>{_votes_table(ctx, trace)}"
        )
        return [_rel(_page(ctx, f"{_slug(answer.id)}.html", f"{answer.id}: evidence", body))]

    def write_run(self, answers: Sequence[Answer], traces: Sequence[Trace], ctx: Context) -> list[str]:
        rows = "".join(
            f'<tr><td><a href="{_slug(a.id)}.html">{escape(a.id)}</a></td><td>{escape(t.question.text)}</td>'
            f"<td>{escape(a.status)}</td><td>{escape(str(a.direction or ''))}</td><td>{a.confidence:.0%}</td></tr>"
            for a, t in zip(answers, traces)
        )
        index = (
            '<h1>Answers</h1><p><a href="gapmap.html">Evidence gap map</a></p><div class="wrap"><table>'
            '<caption>All questions</caption><thead><tr><th scope="col">Id</th><th scope="col">Question</th>'
            '<th scope="col">Status</th><th scope="col">Direction</th><th scope="col">Confidence</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>"
        )
        return [_rel(_page(ctx, "index.html", "Answers", index)), _rel(self.gap_map(ctx))]

    def gap_map(self, ctx: Context) -> Path:
        tax = ctx.taxonomy
        if tax.empty:
            body = "<h1>Evidence gap map</h1><p>Available once taxonomy/classes.yaml is built.</p>"
            return _page(ctx, "gapmap.html", "Evidence gap map", body)
        docs: dict[tuple[str, str], set[str]] = defaultdict(set)
        for e in ctx.graph.edges.values():
            for s in tax.classes_of(e["subject"]):
                for o in tax.classes_of(e["object"]):
                    docs[(s.class_id, o.class_id)].add(e.get("source_document", ""))
        causes, outcomes = tax.of_kind("cause"), tax.of_kind("outcome")
        head = "".join(f'<th scope="col">{escape(o.label)}</th>' for o in outcomes)
        body_rows = "".join(
            f'<tr><th scope="row">{escape(c.label)}</th>'
            + "".join(f"<td>{len(docs[(c.id, o.id)]) or 'gap'}</td>" for o in outcomes)
            + "</tr>"
            for c in causes
        )
        body = (
            "<h1>Evidence gap map</h1><p>Number of studies with at least one claim from each intervention or condition "
            '(rows) to each outcome (columns). "gap" means the graph has no such claim.</p><div class="wrap"><table>'
            f"<caption>Studies per intervention and outcome</caption><thead><tr><td></td>{head}</tr></thead>"
            f"<tbody>{body_rows}</tbody></table></div>"
        )
        return _page(ctx, "gapmap.html", "Evidence gap map", body)
