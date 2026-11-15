"""Static, script-free evidence pages: one per question, an index, and an evidence gap map.

A question page (ROADMAP item 16) is built from the `Trace` alone, so it shows whatever the current
default strategies produced. Its sections, each a `<section id=...>` with an `<h2>`:

- `answer`: the answer card. Status, direction, evidence certainty and our confidence are separate
  entries, each with a line saying what it measures, so certainty is never read as confidence.
- `studies`: one vote table per study with a counted vote: the study's vote, then each counted
  claim with its quote, comparator, effect, certainty and causal language, and a DOI link.
- `sign-trace`: for every forward edge, cause-side sign x predicate sign x outcome-side sign, the
  effect the interpreter read, and the rule that read it; then the per-study tally.
- `excluded`: forward edges that bear on the question but were not counted, with the reason, and
  near misses (shown, never voted).
- `reversed`: edges from the outcome to the cause, never counted.

An empty section says so rather than disappearing, so every page has the same outline.
"""

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
from camoreasoning.contracts import Answer, EdgeVote, Trace
from camoreasoning.registry import register
from camoreasoning.signs import compose, predicate_sign

EFFECT = {1: "increase", -1: "decrease", 0: "no effect", None: "unsigned"}
SIGN = {1: "+", -1: "&minus;", 0: "0", None: "none"}
# Verdict.doc_effects: one effect per study with a signed or null vote; None is a tie inside the study.
STUDY_VOTE = {1: "increase", -1: "decrease", 0: "no effect", None: "mixed within the study"}
NO_STUDY_VOTE = "none: its counted claims carry no sign"
SECTIONS = ("answer", "studies", "sign-trace", "excluded", "reversed")  # ids every question page carries
# Plain-language reading of the interpreters' EdgeVote.reason tags; an unknown tag is shown as is.
REASONS = {
    "signed": "signed claim: cause-side sign × predicate sign × outcome-side sign",
    "unsigned_predicate": "association read as positive, so the node directions carry the sign",
    "associational": "association signed through the node directions; it is not shown to be causal",
    "reference_locus": "sign flipped: the sentence places the extreme at the undisturbed reference",
    "double_negation": "sign flipped: a negative predicate on a negative outcome is one negation, not two",
    "null": "null finding: tested, and no effect was found",
    "unchanged_outcome": "the outcome did not change",
    "unsigned_association": "association that names no direction: counted, with no sign",
    "unchanged_cause": "the cause did not change, so the claim gives no sign",
    "non_directional_predicate": "the relation names no direction (for example moderates or mediates)",
    "unsigned_difference": "a significant difference in a direction the claim does not state",
    "prevented_change": "the claim names a change that did not happen",
    "reversed": "the claim runs from the outcome to the cause",
}
CARD = (  # (label, what it measures): kept apart so certainty is never read as confidence
    ("Status", "whether the graph holds any claim that bears on the question"),
    ("Direction", "which way the counted studies point"),
    ("Evidence certainty", "how far the evidence can be trusted, graded from the studies"),
    ("Our confidence", "our estimate of the chance that this answer is right"),
)


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


def _words(tag: str | None) -> str:
    return escape((tag or "not stated").replace("_", " "))


def _reason(tag: str) -> str:
    return escape(REASONS.get(tag, tag.replace("_", " ")))


def _claim(ctx: Context, eid: str) -> str:
    """Subject, predicate and object, then the source sentence as a quote."""
    g = ctx.graph
    e = g.edges[eid]
    return (
        f"{escape(g.subject(eid).get('name', ''))} <em>{_words(e.get('predicate'))}</em> "
        f"{escape(g.object(eid).get('name', ''))}<blockquote>{escape(e.get('original_sentence', ''))}</blockquote>"
    )


def _comparator(ctx: Context, eid: str) -> str:
    parts = []
    for c in ctx.graph.edges[eid].get("comparator") or []:
        desc = c.get("comparator_description")
        parts.append(_words(c.get("comparator_type")) + (f": {escape(desc)}" if desc else ""))
    return "; ".join(parts) or "not stated"


_ITALIC = re.compile(r"&lt;i&gt;((?:(?!&lt;/?i&gt;).)+?)&lt;/i&gt;", re.S)


def _title(text: str) -> str:
    """Escaped paper title; each balanced `<i>...</i>` pair (taxon names in CAMO titles) becomes `<em>`.

    Escapes first, then restores only the exact escaped pair, so no other markup survives; a lone or nested
    tag stays escaped."""
    return _ITALIC.sub(r"<em>\1</em>", escape(text))


def _study(doc: dict, doc_id: str) -> str:
    """First author and year, title, and a DOI link (the document id where the record has no DOI)."""
    who = escape(f"{(doc.get('authors') or ['Unknown'])[0].split(',')[0]} {doc.get('year', '')}".strip())
    title = f" <cite>{_title(doc['title'])}</cite>" if doc.get("title") else ""
    doi = doc.get("doi")
    link = f'<a href="https://doi.org/{escape(doi)}">doi:{escape(doi)}</a>' if doi else escape(doc_id)
    return f"{who}.{title} {link}"


def _wrap(cid: str, caption: str, rest: str, cls: str = "") -> str:
    """A table in a horizontal scroller. The scroller takes keyboard focus and is named by the caption
    (WCAG 2.1.1), because a wide table can overflow a 320 px screen and hold no link to tab to."""
    table = f'<table class="{cls}">' if cls else "<table>"
    return (
        f'<div class="wrap" tabindex="0" role="region" aria-labelledby="{cid}">{table}'
        f'<caption id="{cid}">{caption}</caption>{rest}</table></div>'
    )


def _table(cid: str, caption: str, cols: Sequence[str], rows: Sequence[str]) -> str:
    head = "".join(f'<th scope="col">{c}</th>' for c in cols)
    return _wrap(cid, caption, f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody>")


def _section(sid: str, title: str, intro: str, content: str) -> str:
    return (
        f'<section id="{sid}" aria-labelledby="{sid}-h"><h2 id="{sid}-h">{title}</h2><p>{intro}</p>{content}</section>'
    )


def _card(answer: Answer, trace: Trace) -> str:
    values = (
        answer.status.replace("_", " "),
        answer.direction.replace("_", " ") if answer.direction else "none: no evidence to point either way",
        answer.certainty.replace("_", " ") if answer.certainty else "not graded: no evidence to grade",
        f"{answer.confidence:.0%}",
    )
    items = [(k, escape(v), what) for (k, what), v in zip(CARD, values)]
    if answer.searched_for:
        items.append(("Searched for", escape(answer.searched_for), "what the graph was searched for"))
    card = "".join(f'<dt>{k}</dt><dd>{v} <span class="muted">({what})</span></dd>' for k, v, what in items)
    error = f"<p><strong>This question failed part-way:</strong> {escape(trace.error)}</p>" if trace.error else ""
    return _section(
        "answer",
        "Answer",
        "Direction, evidence certainty and our confidence are separate measures: strong evidence can still "
        "leave us unsure, and weak evidence can point clearly one way.",
        f"<p>{escape(answer.answer)}</p><dl>{card}</dl>{error}",
    )


def _studies(ctx: Context, votes: Sequence[EdgeVote], doc_effects: dict[str, int | None]) -> str:
    by_doc: dict[str, list[EdgeVote]] = defaultdict(list)
    for v in votes:
        if v.included:
            by_doc[v.doc_id].append(v)
    cols = ("Claim and quote", "Comparator", "Effect on outcome", "Certainty, language", "Edge")
    tables = []
    for n, (doc_id, vs) in enumerate(by_doc.items(), 1):
        vote = STUDY_VOTE[doc_effects[doc_id]] if doc_id in doc_effects else NO_STUDY_VOTE
        rows = [
            f"<tr><td>{_claim(ctx, v.edge_id)}</td><td>{_comparator(ctx, v.edge_id)}</td><td>{EFFECT[v.effect]}</td>"
            f"<td>{_words(v.certainty_grade)}, {_words(v.causal_language)}</td>"
            f"<td><code>{escape(v.edge_id)}</code></td></tr>"
            for v in vs
        ]
        caption = f"{_study(ctx.graph.doc(vs[0].edge_id), doc_id)}. Study vote: <strong>{vote}</strong>"
        tables.append(_table(f"study-{n}", caption, cols, rows))
    return _section(
        "studies",
        "Votes by study",
        "One table per study with a counted claim. Each study casts one vote, whatever its number of claims.",
        "".join(tables) or "<p>None: no claim was counted.</p>",
    )


def _sign_trace(ctx: Context, trace: Trace, votes: Sequence[EdgeVote], doc_effects: dict[str, int | None]) -> str:
    cand, g, rows = trace.candidates, ctx.graph, []
    for v in votes:
        if v.reason == "reversed" or cand is None or v.edge_id in cand.reversed:
            continue
        e = g.edges[v.edge_id]
        cause, outcome = cand.cause_nodes.get(e["subject"]), cand.outcome_nodes.get(e["object"])
        pred = predicate_sign(e.get("predicate"))
        rows.append(
            f"<tr><td>{escape(g.subject(v.edge_id).get('name', ''))} <em>{_words(e.get('predicate'))}</em> "
            f"{escape(g.object(v.edge_id).get('name', ''))}<br><code>{escape(v.edge_id)}</code></td>"
            f"<td>{SIGN[cause]}</td><td>{SIGN[pred]}</td><td>{SIGN[outcome]}</td>"
            f"<td>{SIGN[compose(cause, pred, outcome)]}</td><td>{EFFECT[v.effect]}</td>"
            f"<td>{'yes' if v.included else 'no'}</td><td>{_reason(v.reason)}</td></tr>"
        )
    cols = ("Claim", "Cause side", "Predicate", "Outcome side", "Product", "Read as", "Counted", "Rule")
    table = (
        _table("sign-trace-t", "Sign of each claim on the question's outcome", cols, rows) if rows else "<p>None.</p>"
    )
    tally: dict[str, int] = defaultdict(int)
    for effect in doc_effects.values():
        tally[STUDY_VOTE[effect]] += 1
    verdict = trace.verdict
    summary = ""
    if tally and verdict is not None:
        counts = ", ".join(f"{n} {k}" for k, n in sorted(tally.items(), key=lambda x: (-x[1], x[0])))
        direction = (verdict.direction or "none").replace("_", " ")
        summary = (
            f"<p>Study votes: {escape(counts)}. Direction: <strong>{escape(direction)}</strong>, "
            f"with {verdict.agreement:.0%} of studies agreeing.</p>"
        )
    return _section(
        "sign-trace",
        "Sign trace",
        "How each claim's sign was read. A sign is relative to the question: + means the claim's node moves the "
        "same way as the question's cause or outcome, &minus; the opposite way, 0 unchanged, and none no sign. "
        "The product of the three is the schema's reading; the rule column says when the claim was read otherwise.",
        table + summary,
    )


def _excluded(ctx: Context, trace: Trace, votes: Sequence[EdgeVote]) -> str:
    rows = [
        f"<tr><td>{_claim(ctx, v.edge_id)}</td><td>{_reason(v.reason)}</td>"
        f"<td>{_study(ctx.graph.doc(v.edge_id), v.doc_id)}<br><code>{escape(v.edge_id)}</code></td></tr>"
        for v in votes
        if not v.included and v.reason != "reversed"
    ]
    near = trace.candidates.near_miss if trace.candidates else ()
    rows += [
        f"<tr><td>{_claim(ctx, eid)}</td><td>near miss: close to the question, shown but never counted</td>"
        f"<td>{_study(ctx.graph.doc(eid), ctx.graph.edges[eid].get('source_document', ''))}<br>"
        f"<code>{escape(eid)}</code></td></tr>"
        for eid in near
    ]
    content = (
        _table("excluded-t", "Claims not counted", ("Claim and quote", "Why not counted", "Source"), rows)
        if rows
        else ""
    )
    return _section(
        "excluded",
        "Excluded edges",
        "Claims that bear on the question but cast no vote.",
        content or "<p>None.</p>",
    )


def _reversed(ctx: Context, trace: Trace) -> str:
    ids = trace.candidates.reversed if trace.candidates else ()
    rows = [
        f"<tr><td>{_claim(ctx, eid)}</td>"
        f"<td>{_study(ctx.graph.doc(eid), ctx.graph.edges[eid].get('source_document', ''))}<br>"
        f"<code>{escape(eid)}</code></td></tr>"
        for eid in ids
    ]
    return _section(
        "reversed",
        "Reversed edges",
        "Claims that run from the outcome to the cause. They say the outcome affects the cause, not the "
        "other way round, so they are never counted.",
        _table("reversed-t", "Claims from outcome to cause", ("Claim and quote", "Source"), rows)
        if rows
        else "<p>None.</p>",
    )


@register("extras", "baseline")
class HtmlExtras(ExtrasWriter):
    def write_question(self, answer: Answer, trace: Trace, ctx: Context) -> list[str]:
        votes = trace.verdict.votes if trace.verdict else ()
        doc_effects = dict(trace.verdict.doc_effects) if trace.verdict else {}
        body = (
            f"<h1>{escape(trace.question.text or answer.id)}</h1>"
            + _card(answer, trace)
            + _studies(ctx, votes, doc_effects)
            + _sign_trace(ctx, trace, votes, doc_effects)
            + _excluded(ctx, trace, votes)
            + _reversed(ctx, trace)
        )
        return [_rel(_page(ctx, f"{_slug(answer.id)}.html", f"{answer.id}: evidence", body))]

    def write_run(self, answers: Sequence[Answer], traces: Sequence[Trace], ctx: Context) -> list[str]:
        rows = "".join(
            f'<tr><td><a href="{_slug(a.id)}.html">{escape(a.id)}</a></td><td>{escape(t.question.text)}</td>'
            f"<td>{escape(a.status)}</td><td>{escape(str(a.direction or ''))}</td><td>{a.confidence:.0%}</td></tr>"
            for a, t in zip(answers, traces)
        )
        cols = ("Id", "Question", "Status", "Direction", "Confidence")
        index = '<h1>Answers</h1><p><a href="gapmap.html">Evidence gap map</a></p>' + _table(
            "all-t", "All questions", cols, [rows]
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
            '(rows) to each outcome (columns). "gap" means the graph has no such claim.</p>'
            + _wrap(
                "grid-t",
                "Studies per intervention and outcome",
                f'<thead><tr><th scope="col">Intervention or condition</th>{head}</tr></thead>'
                f"<tbody>{body_rows}</tbody>",
            )
        )
        return _page(ctx, "gapmap.html", "Evidence gap map", body)
