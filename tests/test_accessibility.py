"""Item 19: the generated pages meet the scripted part of the WCAG 2.2 AA audit (`scripts/a11y_audit.py`).

Writes every page the default extras writer makes (practice questions on the real taxonomy, the fixture
questions, the gap map, its cells and the limits page), plus the baseline writer's gap map, and runs the
static audit over them and over `product/style.css`. The auditor is itself checked on small broken pages,
so a check that silently stopped finding anything would fail here.
"""

from __future__ import annotations

import pytest
from scripts.a11y_audit import audit_css, audit_dir, audit_html, contrast, schemes

from camoreasoning.answers import load_questions
from camoreasoning.config import PRODUCT_DIR, ROOT
from camoreasoning.pipeline import Pipeline
from camoreasoning.registry import get
from camoreasoning.strategies import DEFAULTS
from camoreasoning.taxonomy import load_taxonomy


def page(body: str, lang: str = "en", title: str = "t") -> str:
    return f'<!doctype html><html lang="{lang}"><head><title>{title}</title></head><body>{body}</body></html>'


def test_default_pages_pass(make_ctx, questions):
    ctx = make_ctx()
    answers, traces = Pipeline(ctx).run(questions)
    get("extras", DEFAULTS["extras"]).write_run(answers, traces, ctx)
    ctx = make_ctx(tax=load_taxonomy())
    answers, traces = Pipeline(ctx).run(load_questions(ROOT / "questions.yaml"))
    get("extras", DEFAULTS["extras"]).write_run(answers, traces, ctx)
    names = {p.name for p in ctx.out_dir.glob("*.html")}
    assert {"index.html", "gapmap.html", "gapcells.html", "limits.html"} <= names and len(names) > 4
    assert audit_dir(ctx.out_dir) == []


def test_baseline_gap_map_passes(make_ctx, questions):
    ctx = make_ctx()
    answers, traces = Pipeline(ctx).run(questions[:3])
    get("extras", "baseline").write_run(answers, traces, ctx)
    assert audit_dir(ctx.out_dir) == []


def test_contrast_matches_wcag_reference_values():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)
    assert contrast("#777", "#fff") < 4.5


def test_stylesheet_tokens_are_read_for_both_schemes():
    s = schemes((PRODUCT_DIR / "style.css").read_text(encoding="utf-8"))
    assert s["light"]["bg"] == "#fbfbfd" and s["dark"]["bg"] == "#0f1115"
    assert {"fg", "muted", "link", "line", "d1", "d4"} <= s["dark"].keys()


def test_low_contrast_is_found():
    css = ":root { --fg: #1a1a1a; --bg: #ffffff; --muted: #aaaaaa; --line: #767676; --link: #0b57d0; "
    css += "--d1: #f3f7fe; --d2: #e6effc; --d3: #dae6fa; --d4: #ccdcf7; }"
    found = audit_css(css)
    assert found and all("--muted #aaaaaa" in f for f in found), found
    dark = css + " @media (prefers-color-scheme: dark) { :root { --link: #1a1a40; --bg: #121212; } }"
    assert any(f.startswith("style.css: dark --link") for f in audit_css(dark))


@pytest.mark.parametrize(
    ("html", "finding"),
    [
        (page("<h1>a</h1>", lang=""), "html has no lang"),
        (page("<h1>a</h1>", title=""), "no title"),
        (page("<h2>a</h2>"), "0 h1 elements"),
        (page("<h1>a</h1><h3>b</h3>"), "heading skips from h1 to h3"),
        (page("<h1>a</h1><table><caption>c</caption><tr><th>x</th></tr></table>"), "a th without scope"),
        (page("<h1>a</h1><table><tr><td>x</td></tr></table>"), "a table without caption"),
        (page("<h1>a</h1><table><caption>c</caption><thead><tr><td></td></tr></thead></table>"), "a td in a table"),
        (page('<h1>a</h1><div class="wrap"><table><caption>c</caption></table></div>'), "a scrolling table"),
        (page('<h1 id="x">a</h1><p id="x"></p>'), "duplicate ids: x"),
        (page('<h1>a</h1><a href="#nowhere">b</a>'), "in-page links to missing ids: nowhere"),
        (page('<h1>a</h1><div aria-labelledby="gone"></div>'), "aria-labelledby names missing ids: gone"),
        (page('<h1>a</h1><a href="x.html"></a>'), "a link with no text"),
        (page("<h1>a</h1><script>1</script>"), "a script"),
    ],
)
def test_auditor_finds(html, finding):
    assert any(f.startswith(finding) for f in audit_html(html)), audit_html(html)


def test_named_focusable_scroller_passes():
    table = '<div class="wrap" tabindex="0" role="region" aria-labelledby="c"><table><caption id="c">c</caption>'
    table += '<thead><tr><th scope="col">x</th></tr></thead></table></div>'
    assert audit_html(page(f'<h1>a</h1><h2>b</h2><a href="#c"><span>go</span></a>{table}')) == []
