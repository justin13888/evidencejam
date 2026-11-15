"""Linker `phrase`: the stem fallback reaches inflected wording, alongside the node fallback."""

from __future__ import annotations

import pytest

from camoreasoning import registry
from camoreasoning.contracts import ParsedQuestion, Question
from camoreasoning.strategies.linker import phrase
from camoreasoning.strategies.linker.baseline import _index
from camoreasoning.taxonomy import TaxonClass, Taxonomy

CLASSES = {
    "soil_inoculation": TaxonClass("soil_inoculation", "cause", "soil inoculation", ("inoculation", "inoculum")),
    "wetland_creation": TaxonClass(
        "wetland_creation",
        "cause",
        "wetland creation & marsh restoration",
        ("wetland restoration", "marsh restoration"),
    ),
    "plant_growth": TaxonClass("plant_growth", "outcome", "plant growth", ("growth",)),
}


@pytest.fixture
def ctx(make_ctx):
    return make_ctx(tax=Taxonomy(CLASSES))


def link(ctx, cause: str, outcome: str = "plant growth"):
    q = Question("q", f"What effect does {cause} have on {outcome}?")
    return registry.get("linker", "phrase").link([ParsedQuestion(q, cause, outcome, True)], ctx)[0]


@pytest.mark.parametrize(
    ("text", "cid"),
    [("inoculating soil with microbes", "soil_inoculation"), ("restoring wetlands and marshes", "wetland_creation")],
)
def test_stem_fallback_links_inflected_wording(ctx, text, cid):
    side = link(ctx, text).cause
    assert [r.id for r in side.classes] == [cid]
    assert side.classes[0].score == phrase.STEM_SCORE


def test_stem_side_keeps_node_fallback_nodes(ctx):
    text = "restoring wetlands"
    nodes = phrase.PhraseFallbackLinker._nodes(text, "cause", ctx, _index(ctx))[0].nodes
    assert nodes, "this wording should match some graph nodes"
    side = link(ctx, text).cause
    assert [r.id for r in side.classes] == ["wetland_creation"]
    assert side.nodes == nodes


def test_stem_fallback_off_leaves_side_unlinked_to_classes(ctx, monkeypatch):
    monkeypatch.setattr(phrase, "STEM_FALLBACK", False)
    assert not link(ctx, "inoculating soil with microbes").cause.classes


def test_linked_side_is_unchanged(ctx):
    side = link(ctx, "soil inoculation").cause
    assert [(r.id, r.score) for r in side.classes] == [("soil_inoculation", 1.0)]
    assert not side.nodes


def test_stem_needs_enough_coverage(ctx):
    # "soil" alone is a small share of this side's IDF mass: no class.
    assert not link(ctx, "soil sampled on rainy afternoons near the old quarry").cause.classes
