"""Frozen stage interfaces. One ROADMAP task = one stage; experiments add strategies, never change these.

Each strategy subclasses one ABC, is decorated with `@register(<stage>, "<name>")` and lives in
`strategies/<stage>/<name>.py`. tests/contracts/ checks every registered strategy against the
invariants written in each docstring, so a new strategy is verified the moment it is registered.
LLM use goes through `ctx.llm` only (metered, budgeted); stages marked "0 LLM calls" must not call it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from camoreasoning.config import Settings
from camoreasoning.contracts import (
    Answer,
    Candidates,
    Certainty,
    DevQuestion,
    EdgeVote,
    Features,
    Frame,
    GoldItem,
    ParsedQuestion,
    Question,
    Trace,
    Verdict,
)
from camoreasoning.graph import Graph
from camoreasoning.taxonomy import NodeLabel, Taxonomy

if TYPE_CHECKING:
    from camoreasoning.llm import LLM


@dataclass
class Context:
    """Shared run state. `memo` lets strategies cache derived indexes for the run."""

    graph: Graph
    taxonomy: Taxonomy
    llm: LLM
    settings: Settings
    out_dir: Path
    memo: dict = field(default_factory=dict)


class Stage(ABC):
    stage: ClassVar[str]
    name: ClassVar[str] = ""  # set by @register


# --- runtime --------------------------------------------------------------------------------------


class QuestionParser(Stage):
    """Split a question into cause/outcome spans. 0 LLM calls. Must not raise on any string."""

    stage = "parser"

    @abstractmethod
    def parse(self, question: Question, ctx: Context) -> ParsedQuestion: ...


class ClassLinker(Stage):
    """Map parsed questions to taxonomy classes and/or graph nodes, all questions at once.

    Returns one Frame per input, same order, `frame.parsed is batch[i]`. Ref ids exist in the
    taxonomy (classes) or graph (nodes); polarity in {-1,0,1}. At most ceil(len/25) LLM calls,
    batched. If `ctx.llm` raises LLMError the pipeline falls back to the `baseline` linker.
    """

    stage = "linker"

    @abstractmethod
    def link(self, batch: Sequence[ParsedQuestion], ctx: Context) -> list[Frame]: ...


class Retriever(Stage):
    """Frame -> Candidates. 0 LLM calls. forward edges run cause_nodes -> outcome_nodes, reversed
    edges outcome_nodes -> cause_nodes; the two are disjoint and every id exists in the graph."""

    stage = "retriever"

    @abstractmethod
    def retrieve(self, frame: Frame, ctx: Context) -> Candidates: ...


class EdgeInterpreter(Stage):
    """Read each candidate edge as a vote. 0 LLM calls. Exactly one EdgeVote per forward and reversed
    edge; reversed votes are never `included`; null findings (signs.is_null_finding) have effect 0."""

    stage = "interpreter"

    @abstractmethod
    def interpret(self, candidates: Candidates, ctx: Context) -> tuple[EdgeVote, ...]: ...


class Aggregator(Stage):
    """Votes -> Verdict. 0 LLM calls. status is no_evidence iff no vote is included; direction is
    None iff no_evidence; 0 <= agreement <= 1."""

    stage = "aggregator"

    @abstractmethod
    def aggregate(self, votes: tuple[EdgeVote, ...], candidates: Candidates, ctx: Context) -> Verdict: ...


class Grader(Stage):
    """Evidence certainty for the answer. None iff no_evidence, else one of ANSWER_CERTAINTY."""

    stage = "grader"

    @abstractmethod
    def grade(self, verdict: Verdict, ctx: Context) -> Certainty | None: ...


class Calibrator(Stage):
    """P(answer is correct) in [0, 1], deterministic. Fitted params live under experiments/."""

    stage = "calibrator"

    @abstractmethod
    def confidence(self, features: Features, ctx: Context) -> float: ...

    def fit(self, rows: Sequence[tuple[Features, bool]], ctx: Context) -> dict | None:
        """Optional: learn params from (features, was_correct) on the dev split. Return a JSON-serialisable
        dict; `camoreasoning calibrate` writes it to experiments/calibration/<name>.json for
        `confidence` to load. None = nothing to fit."""
        return None


class Citer(Stage):
    """edge_ids to cite: a subset of the included votes' edges, non-empty iff answered."""

    stage = "citer"

    @abstractmethod
    def cite(self, verdict: Verdict, ctx: Context) -> list[str]: ...


class Renderer(Stage):
    """(answer text, searched_for). Text non-empty; searched_for non-empty iff no_evidence, else None.
    0 LLM calls (decided: answer text is template-rendered, faithful by construction)."""

    stage = "renderer"

    @abstractmethod
    def render(
        self, verdict: Verdict, candidates: Candidates, certainty: Certainty | None, ctx: Context
    ) -> tuple[str, str | None]: ...


class ExtrasWriter(Stage):
    """Write judge-facing files under ctx.out_dir; return paths relative to the repo root (or as given
    if outside it). Static HTML only: lang attribute, <title>, no <script>. Must not raise."""

    stage = "extras"

    @abstractmethod
    def write_question(self, answer: Answer, trace: Trace, ctx: Context) -> list[str]: ...

    def write_run(self, answers: Sequence[Answer], traces: Sequence[Trace], ctx: Context) -> list[str]:
        """Run-level pages (index, gap map, limits). Returned paths are informational."""
        return []


# --- offline (build artifacts before submission; never run by ./run.sh) ------------------------


class TaxonomyBuilder(Stage):
    """Graph -> classes (labels empty or preserved). Unique ids; kind in taxonomy.KINDS."""

    stage = "taxonomy_builder"

    @abstractmethod
    def build(self, ctx: Context) -> Taxonomy: ...


class NodeLabeler(Stage):
    """Assign graph nodes to classes with polarity. Every node_id/class_id exists; polarity valid."""

    stage = "node_labeler"

    @abstractmethod
    def label(self, taxonomy: Taxonomy, ctx: Context) -> list[NodeLabel]: ...


class DevsetBuilder(Stage):
    """Generate questions mirroring the hidden set (template wording, ~1/3 empty, trap-tagged).
    Unique ids; non-empty question text; split in {dev, holdout}."""

    stage = "devset_builder"

    @abstractmethod
    def build(self, taxonomy: Taxonomy, ctx: Context) -> list[DevQuestion]: ...


class GoldLabeler(Stage):
    """Label dev questions INDEPENDENTLY of the answer pipeline: must not import
    camoreasoning.strategies.* (other than its own module) nor camoreasoning.pipeline.
    Output ids are a subset of input ids; edge_ids exist in the graph."""

    stage = "gold_labeler"

    @abstractmethod
    def label(self, items: Sequence[DevQuestion], ctx: Context) -> list[GoldItem]: ...


BASES: dict[str, type[Stage]] = {
    cls.stage: cls
    for cls in (
        QuestionParser, ClassLinker, Retriever, EdgeInterpreter, Aggregator, Grader, Calibrator,
        Citer, Renderer, ExtrasWriter, TaxonomyBuilder, NodeLabeler, DevsetBuilder, GoldLabeler,
    )
}  # fmt: skip
