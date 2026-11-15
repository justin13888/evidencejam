"""Item 20: the honest-limits page matches the one recorded holdout report row for row.

Reads `experiments/calibration/holdout_report.json` (issue #12's single pass) directly and recomputes every
expected row here, so the page is checked against the report, not against `limits.py`'s own helpers.
"""

from __future__ import annotations

import json
import re
from html import unescape

import pytest

from camoreasoning.config import CALIBRATION_DIR, ROOT
from camoreasoning.registry import get
from camoreasoning.strategies.extras import limits

REPORT = json.loads((CALIBRATION_DIR / "holdout_report.json").read_text(encoding="utf-8"))
ITEMS = REPORT["items"]
TAGS = sorted({t for i in ITEMS for t in i["tags"] if t.startswith("trap:")})
N = 3

SECTION = re.compile(r'<section><h3 id="trap-([^"]+)">([^<]+)</h3>(.*?)</section>', re.S)
MISS = re.compile(r'<tr class="miss"><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>')
SUMMARY = re.compile(
    r'<tr><th scope="row"><a href="#trap-([^"]+)">[^<]+</a></th><td>(\d+)</td><td>(\d+)</td><td>(\d+)</td>'
    r"<td>(\d+)%</td></tr>"
)
BIN = re.compile(
    r'<tr class="bin"><th scope="row">([\d.]+)-([\d.]+)</th><td>(\d+)</td><td>([^<]+)</td><td>([^<]+)</td>'
)
FILE = re.compile(r'<tr class="file"><th scope="row">([^<]+)</th><td>(\d+)</td><td>([^<]+)</td><td>([^<]+)</td>'
                  r"<td>([^<]+)</td></tr>")  # fmt: skip


def answer(a: dict | None) -> str:
    if a is None:
        return "no answer"
    rest = [a[k].replace("_", " ") for k in ("direction", "certainty") if a[k]]
    status = a["status"].replace("_", " ")
    return f"{status}: {', '.join(rest)}" if rest else status


def num(x: float | None) -> str:
    return "-" if x is None else f"{x:.3f}"


@pytest.fixture(scope="module")
def html(tmp_path_factory) -> str:
    from camoreasoning.components import Context
    from camoreasoning.config import Settings

    out = tmp_path_factory.mktemp("limits")
    ctx = Context(None, None, None, Settings(), out)
    path = limits.write_limits(ctx)
    assert path.endswith("limits.html")
    return (out / "limits.html").read_text(encoding="utf-8")


def test_report_is_the_recorded_single_pass():
    assert REPORT["split"] == "holdout" and REPORT["pooled"]["n"] == len(ITEMS) == 68
    assert [i["id"] for i in ITEMS] == sorted(i["id"] for i in ITEMS)
    assert TAGS, "the holdout should carry trap tags"


def test_page_is_static_and_states_its_provenance(html):
    assert '<html lang="' in html and "<title>Honest limits</title>" in html and "<script" not in html.lower()
    assert "82fa03d" in html and all(f"#{n}" in html for n in (65, 68, 69))
    assert "not run again" in html


def test_every_trap_tag_lists_its_first_misses_in_id_order(html):
    sections = {f"trap:{tag}": body for tag, _, body in SECTION.findall(html)}
    assert sorted(sections) == TAGS
    for tag in TAGS:
        misses = [i for i in ITEMS if tag in i["tags"] and not i["correct"]]
        want = sorted(misses, key=lambda i: i["id"])[:N]
        rows = MISS.findall(sections[tag])
        assert [unescape(r[0]) for r in rows] == [i["id"] for i in want], tag
        for (qid, question, gold, got, conf), item in zip(rows, want):
            assert unescape(question) == item["question"], qid
            assert unescape(gold) == answer(item["gold"]), qid
            assert unescape(got) == answer(item["predicted"]), qid
            assert conf == ("-" if item["confidence"] is None else f"{item['confidence']:.0%}"), qid
        if not misses:
            assert "No misses on the holdout for this tag." in sections[tag], tag
        elif len(misses) > N:
            assert f"the first {N} of {len(misses)} misses" in sections[tag], tag
        else:
            assert ("the only miss" if len(misses) == 1 else f"all {len(misses)} misses") in sections[tag], tag


def test_each_trap_section_shows_only_the_first_sentence_of_its_why(html):
    """Decision 6: judges see the inventory's first sentence; the later team-note sentences stay hidden."""
    inventory = json.loads((ROOT / "experiments/results/trap_inventory.json").read_text(encoding="utf-8"))
    sections = {f"trap:{tag}": body for tag, _, body in SECTION.findall(html)}
    multi = 0
    for tag in TAGS:
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z'])", inventory[tag[len("trap:") :]]["why"].strip())
        shown = unescape(re.match(r"<p>(.*?)</p>", sections[tag], re.S).group(1))
        assert shown == sentences[0], tag
        for later in sentences[1:]:
            assert later not in unescape(sections[tag]), (tag, later)
        multi += len(sentences) > 1
    assert multi, "at least one holdout trap tag should have later sentences to hide"


def test_summary_rows_match_items_and_by_tag(html):
    rows = {f"trap:{t}": tuple(map(int, rest)) for t, *rest in SUMMARY.findall(html)}
    assert sorted(rows) == TAGS
    for tag in TAGS:
        tagged = [i for i in ITEMS if tag in i["tags"]]
        right = sum(i["correct"] for i in tagged)
        assert rows[tag] == (len(tagged), right, len(tagged) - right, round(100 * right / len(tagged))), tag
        by_tag = REPORT["pooled"]["by_tag"][tag]
        assert by_tag["n"] == len(tagged) and by_tag["accuracy"] == pytest.approx(right / len(tagged), abs=1e-4)


def test_reliability_table_and_ece_miss(html):
    cal = REPORT["pooled"]["calibration"]
    by_bin = {b["bin"]: b for b in cal["bins"]}
    rows = BIN.findall(html)
    assert len(rows) == 10
    for b, (lo, hi, n, mean, acc) in enumerate(rows):
        r = by_bin.get(b, {"n": 0, "mean_conf": None, "accuracy": None})
        assert (float(lo), float(hi)) == pytest.approx((b / 10, (b + 1) / 10))
        assert (int(n), mean, acc) == (r["n"], num(r["mean_conf"]), num(r["accuracy"])), b
    assert sum(int(r[2]) for r in rows) == REPORT["pooled"]["n"]
    ece = re.search(r'<p class="ece">(.*?)</p>', html, re.S).group(1)
    assert REPORT["passes"] is False and cal["ece"] > REPORT["target_ece"] == 0.05
    assert f"<strong>{cal['ece']:.3f}</strong>" in ece and "target of 0.05" in ece and "<strong>misses</strong>" in ece
    assert f"ECE {REPORT['baseline_constant']['ece']:.3f}" in ece
    files = FILE.findall(html)
    assert [f[0] for f in files] == sorted(REPORT["files"])
    for name, n, acc, e, brier in files:
        r = REPORT["files"][name]
        assert (int(n), acc, e, brier) == (
            r["n"], num(r["accuracy"]), num(r["calibration"]["ece"]), num(r["calibration"]["brier"])
        ), name  # fmt: skip


def test_non_goals(html):
    tail = html.split('id="non-goals"', 1)[1]
    assert "<h3>Multi-hop chains</h3>" in tail and "<h3>Effect sizes</h3>" in tail


@pytest.mark.parametrize("content", [None, "{not json", '{"items": 3}', '{"items": [{"tags": 1}]}'])
def test_missing_or_bad_report_does_not_raise(tmp_path, content):
    from camoreasoning.components import Context
    from camoreasoning.config import Settings

    src = tmp_path / "holdout_report.json"
    if content is not None:
        src.write_text(content, encoding="utf-8")
    ctx = Context(None, None, None, Settings(), tmp_path / "out")
    limits.write_limits(ctx, src, tmp_path / "missing.json")
    page = (tmp_path / "out" / "limits.html").read_text(encoding="utf-8")
    assert "missing or unreadable" in page and 'id="non-goals"' in page


def test_gapmap_writes_and_links_the_page(make_ctx):
    ctx = make_ctx()
    paths = get("extras", "gapmap").write_run([], [], ctx)
    assert paths[-1].endswith("limits.html") and (ROOT / paths[-1]).exists()
    assert 'href="limits.html"' in (ctx.out_dir / "gapmap.html").read_text(encoding="utf-8")


def test_page_states_the_confidence_the_shipped_answers_carry(html):
    text = re.sub(r"<[^>]+>", "", html)
    assert (
        "The answers in this run all carry confidence 0.6 (the baseline calibrator); the confidences in the tables "
        "below come from the binned calibrator measured on the holdout." in text
    )
    assert html.index('class="shipped"') < html.index('id="failures"')


def test_a_non_default_calibrator_is_named_instead_of_the_constant():
    body = limits.render(None, {}, "binned")
    assert "all carry confidence 0.6" not in body and "<code>binned</code> calibrator;" in body
