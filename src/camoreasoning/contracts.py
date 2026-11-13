"""Data passed between stages. Frozen: strategies consume and produce exactly these types.

Flow per question: Question -> ParsedQuestion -> Frame -> Candidates -> [EdgeVote] -> Verdict
-> (certainty, Features -> confidence, edge_ids, text) -> Answer (+ Trace for extras).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["answered", "no_evidence"]
Direction = Literal["increase", "decrease", "no_effect", "mixed", "unclear"]
Certainty = Literal["high", "moderate", "low", "very_low"]
LinkVia = Literal["regex", "lexical", "embedding", "llm", "fallback", "none"]


@dataclass(frozen=True)
class Question:
    id: str
    text: str


@dataclass(frozen=True)
class ParsedQuestion:
    """Surface parse. `cause_text`/`outcome_text` are spans of the question (None if not found)."""

    question: Question
    cause_text: str | None
    outcome_text: str | None
    template_hit: bool  # matched the hidden-set template "What effect does X have on Y?"


@dataclass(frozen=True)
class Ref:
    """A matched taxonomy class or graph node. polarity in {-1, 0, 1} (see taxonomy.py)."""

    id: str
    polarity: int = 1
    score: float = 1.0


@dataclass(frozen=True)
class Side:
    """One side of the question. Retrieval uses nodes of `classes` (via taxonomy) plus `nodes`."""

    text: str | None
    classes: tuple[Ref, ...] = ()
    nodes: tuple[Ref, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.classes or self.nodes)


@dataclass(frozen=True)
class Frame:
    parsed: ParsedQuestion
    cause: Side
    outcome: Side
    via: LinkVia
    margin: float  # linker's confidence gap (best vs runner-up), feeds calibration


@dataclass(frozen=True)
class Candidates:
    """Edges bearing on the frame. forward: cause->outcome; reversed: outcome->cause;
    near_miss: shown to users/searched_for only, never voted."""

    frame: Frame
    cause_nodes: dict[str, int]  # node_id -> polarity relative to the question's cause
    outcome_nodes: dict[str, int]  # node_id -> polarity relative to the question's outcome
    forward: tuple[str, ...] = ()
    reversed: tuple[str, ...] = ()
    near_miss: tuple[str, ...] = ()


@dataclass(frozen=True)
class EdgeVote:
    """One edge's reading for this question. effect: +1 increase, -1 decrease, 0 null, None unsigned."""

    edge_id: str
    doc_id: str
    effect: int | None
    included: bool  # counts toward the verdict
    reason: str  # short machine tag, e.g. "signed", "null", "unsigned_predicate", "reversed"
    certainty_grade: str | None = None
    causal_language: str | None = None


@dataclass(frozen=True)
class Verdict:
    status: Status
    direction: Direction | None  # None iff status == "no_evidence"
    votes: tuple[EdgeVote, ...]
    doc_effects: tuple[tuple[str, int | None], ...] = ()  # one (doc_id, effect) per document
    agreement: float = 0.0  # share of documents agreeing with `direction`
    notes: tuple[str, ...] = ()

    @property
    def included(self) -> tuple[EdgeVote, ...]:
        return tuple(v for v in self.votes if v.included)


@dataclass(frozen=True)
class Features:
    """Everything the calibrator may use. Add fields only by consensus (frozen contract)."""

    status: Status
    direction: Direction | None
    certainty: Certainty | None
    n_docs: int
    n_edges: int
    agreement: float
    null_share: float
    n_reversed: int
    link_via: LinkVia
    link_margin: float
    template_hit: bool


@dataclass
class Answer:
    """One answers.json entry (README "Answer format"). `trace` is never serialized there."""

    id: str
    status: Status
    answer: str
    confidence: float
    direction: Direction | None = None
    certainty: Certainty | None = None
    edge_ids: list[str] = field(default_factory=list)
    searched_for: str | None = None
    extras: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "status": self.status,
            "answer": self.answer,
            "direction": self.direction,
            "confidence": round(float(self.confidence), 4),
            "certainty": self.certainty,
            "edge_ids": list(self.edge_ids),
            "searched_for": self.searched_for,
        }
        if self.extras:
            d["extras"] = list(self.extras)
        return d


@dataclass(frozen=True)
class Trace:
    """Everything that produced an Answer; handed to ExtrasWriter. Fields may be None on failure."""

    question: Question
    frame: Frame | None = None
    candidates: Candidates | None = None
    verdict: Verdict | None = None
    features: Features | None = None
    error: str | None = None


@dataclass(frozen=True)
class DevQuestion:
    id: str
    question: str
    tags: tuple[str, ...] = ()  # e.g. "empty", "answerable", "trap:reversed", "trap:null"
    split: Literal["dev", "holdout"] = "dev"
    meta: dict = field(default_factory=dict)  # generator hints (class ids, ...); never read by the pipeline


@dataclass(frozen=True)
class GoldItem:
    """A labelled dev question. Unlabelled items have status None and are skipped by eval."""

    id: str
    question: str
    status: Status | None
    direction: Direction | None = None
    certainty: Certainty | None = None
    edge_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    split: Literal["dev", "holdout"] = "dev"
    source: str = ""  # "llm:<model>", "human:<initials>"
