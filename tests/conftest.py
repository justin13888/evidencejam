"""Shared fixtures. No test touches the network except tests/robustness via a local fake server."""

from __future__ import annotations

from pathlib import Path

import pytest

from camoreasoning.components import Context
from camoreasoning.config import ROOT, Settings
from camoreasoning.contracts import Question
from camoreasoning.graph import load_graph
from camoreasoning.llm import LLM
from camoreasoning.registry import get
from camoreasoning.taxonomy import Taxonomy, load_taxonomy

FIXTURES = Path(__file__).parent / "fixtures"

FUZZ = [
    "", " ", "?", "on", "What effect does  have on ?", "What effect does X have on", "🦝 " * 50,
    "What effect does “mulch” have on ‘invasive’ abundance?", "x" * 5000, "What effect does on on on have on on?",
    "DROP TABLE edges; --", "What effect does mulch have on mulch?", "​​", "What\neffect\ndoes fire have on biomass",
]  # fmt: skip


@pytest.fixture(scope="session")
def graph():
    return load_graph()


@pytest.fixture(scope="session")
def taxonomy(graph) -> Taxonomy:
    base = load_taxonomy(FIXTURES / "taxonomy")
    ctx = Context(graph, base, LLM(Settings()), Settings(), ROOT / ".cache" / "test")
    return Taxonomy(base.classes, tuple(get("node_labeler", "baseline").label(base, ctx)), base.version)


@pytest.fixture
def make_ctx(graph, taxonomy, tmp_path):
    def make(settings: Settings | None = None, tax: Taxonomy | None = None) -> Context:
        s = settings or Settings()
        return Context(graph, taxonomy if tax is None else tax, LLM(s), s, tmp_path / "outputs")

    return make


@pytest.fixture(scope="session")
def questions(taxonomy) -> list[Question]:
    """Template questions over every fixture class pair, practice questions, and fuzz strings."""
    from camoreasoning.answers import load_questions

    qs = [Question(f"T-{c.id}-{o.id}", f"What effect does {c.label.lower()} have on {o.label.lower()}?")
          for c in taxonomy.of_kind("cause") for o in taxonomy.of_kind("outcome")]  # fmt: skip
    qs += load_questions(ROOT / "questions.yaml")
    qs += [Question(f"F-{i}", s) for i, s in enumerate(FUZZ)]
    return qs
