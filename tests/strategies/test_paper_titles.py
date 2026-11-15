"""Issue #107: CAMO paper titles carry `<i>...</i>` around taxon names; pages show them as emphasis, not as
literal escaped tags, and no other markup in a title gets through."""

from __future__ import annotations

import pytest

from camoreasoning.strategies.extras.baseline import _study, _title


@pytest.mark.parametrize(
    ("raw", "html"),
    [
        ("on a <i>Kalmia</i>-dominated site", "on a <em>Kalmia</em>-dominated site"),
        ("<i>Pinus</i> and <i>Picea</i>", "<em>Pinus</em> and <em>Picea</em>"),
        ("plain & simple", "plain &amp; simple"),
        ("a lone <i>tag", "a lone &lt;i&gt;tag"),
        ("a lone </i>tag", "a lone &lt;/i&gt;tag"),
        ("<i></i>", "&lt;i&gt;&lt;/i&gt;"),
        ("<i><script>x</script></i>", "<em>&lt;script&gt;x&lt;/script&gt;</em>"),
        ('<i class="x">y</i>', "&lt;i class=&quot;x&quot;&gt;y&lt;/i&gt;"),
        ("<I>upper</I>", "&lt;I&gt;upper&lt;/I&gt;"),
    ],
)
def test_title_whitelists_only_balanced_italics(raw, html):
    assert _title(raw) == html


def test_study_cite_renders_italics():
    doc = {"authors": ["Doe, J."], "year": 2001, "title": "Growth of <i>Kalmia</i>", "doi": "10.1/x"}
    out = _study(doc, "d1")
    assert "<cite>Growth of <em>Kalmia</em></cite>" in out and "&lt;i&gt;" not in out


def test_no_graph_title_shows_literal_tags(graph):
    for doc_id, doc in graph.docs.items():
        if doc.get("title"):
            out = _study(doc, doc_id)
            assert "&lt;i&gt;" not in out and "&lt;/i&gt;" not in out, doc_id
