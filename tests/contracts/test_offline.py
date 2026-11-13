"""Contract suite for offline stages (taxonomy, labels, devset, gold), over every registered strategy.
Strategies that need the LLM are exercised only when BRINE_* is set (skipped otherwise)."""

from __future__ import annotations

import ast
import inspect

import pytest

from camoreasoning import registry
from camoreasoning.contracts import DevQuestion, GoldItem
from camoreasoning.llm import LLMError
from camoreasoning.schema import ANSWER_CERTAINTY, DIRECTIONS, STATUSES
from camoreasoning.taxonomy import KINDS, Taxonomy, validate_taxonomy


def call(fn, *a):
    try:
        return fn(*a)
    except LLMError as e:
        pytest.skip(f"needs LLM: {e}")


@pytest.mark.parametrize("name", registry.names("taxonomy_builder"))
def test_taxonomy_builder(name, make_ctx):
    tax = call(registry.get("taxonomy_builder", name).build, make_ctx())
    assert isinstance(tax, Taxonomy)
    assert all(c.kind in KINDS and c.label for c in tax.classes.values())
    assert not validate_taxonomy(tax, set(make_ctx().graph.nodes))


@pytest.mark.parametrize("name", registry.names("node_labeler"))
def test_node_labeler(name, make_ctx, taxonomy):
    ctx = make_ctx()
    labels = call(registry.get("node_labeler", name).label, taxonomy, ctx)
    assert not validate_taxonomy(Taxonomy(taxonomy.classes, tuple(labels)), set(ctx.graph.nodes))


@pytest.mark.parametrize("name", registry.names("devset_builder"))
def test_devset_builder(name, make_ctx, taxonomy):
    items = call(registry.get("devset_builder", name).build, taxonomy, make_ctx())
    assert all(isinstance(i, DevQuestion) and i.question.strip() and i.split in ("dev", "holdout") for i in items)
    assert len({i.id for i in items}) == len(items)
    assert call(registry.get("devset_builder", name).build, Taxonomy(), make_ctx()) is not None


@pytest.mark.parametrize("name", registry.names("gold_labeler"))
def test_gold_labeler(name, make_ctx, taxonomy):
    ctx = make_ctx()
    items = registry.get("devset_builder", "baseline").build(taxonomy, ctx)[:10]
    gold = call(registry.get("gold_labeler", name).label, items, ctx)
    assert {g.id for g in gold} <= {i.id for i in items}
    for g in gold:
        assert isinstance(g, GoldItem) and g.status in STATUSES
        assert g.direction is None or g.direction in DIRECTIONS
        assert g.certainty is None or g.certainty in ANSWER_CERTAINTY
        assert all(e in ctx.graph.edges for e in g.edge_ids)


@pytest.mark.parametrize("name", registry.names("gold_labeler"))
def test_gold_labeler_is_independent_of_the_pipeline(name):
    """Gold must not be produced by the code it grades (non-circular eval)."""
    mod = inspect.getmodule(type(registry.get("gold_labeler", name)))
    tree = ast.parse(inspect.getsource(mod))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    bad = {m for m in imported if m == "camoreasoning.pipeline" or (m.startswith("camoreasoning.strategies.")
           and not m.startswith("camoreasoning.strategies.gold_labeler"))}  # fmt: skip
    assert not bad, bad
