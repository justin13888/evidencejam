"""Taxonomy artifact: broad classes questions are asked in, and node -> class labels with polarity.

Files (taxonomy/, committed, built offline):
  classes.yaml       {version, classes: [{id, kind: cause|outcome|both, label, synonyms: [], description}]}
  node_labels.jsonl  one {node_id, class_id, polarity, score, source} per line

`polarity` is the node's state relative to the class concept, qualifier already folded in:
"Increased invasive cover" -> invasive_abundance +1; "Removal of buckthorn" -> invasive_abundance -1;
"Absence of mulch" -> mulch -1; "No change in X" -> X 0. An edge's effect for a question is then
q_cause_pol x subject_pol x predicate_sign x object_pol x q_outcome_pol.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from camoreasoning.config import TAXONOMY_DIR

KINDS = ("cause", "outcome", "both")
POLARITIES = (-1, 0, 1)


@dataclass(frozen=True)
class TaxonClass:
    id: str
    kind: str
    label: str
    synonyms: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class NodeLabel:
    node_id: str
    class_id: str
    polarity: int
    score: float = 1.0
    source: str = ""


@dataclass(frozen=True)
class Taxonomy:
    classes: dict[str, TaxonClass] = field(default_factory=dict)
    labels: tuple[NodeLabel, ...] = ()
    version: str = "0"

    def __post_init__(self):
        by_class: dict[str, list[NodeLabel]] = defaultdict(list)
        by_node: dict[str, list[NodeLabel]] = defaultdict(list)
        for lb in self.labels:
            by_class[lb.class_id].append(lb)
            by_node[lb.node_id].append(lb)
        object.__setattr__(self, "_by_class", dict(by_class))
        object.__setattr__(self, "_by_node", dict(by_node))

    @property
    def empty(self) -> bool:
        return not self.classes

    def of_kind(self, kind: str) -> list[TaxonClass]:
        return [c for c in self.classes.values() if c.kind in (kind, "both")]

    def nodes_of(self, class_id: str) -> list[NodeLabel]:
        return self._by_class.get(class_id, [])

    def classes_of(self, node_id: str) -> list[NodeLabel]:
        return self._by_node.get(node_id, [])


def load_taxonomy(directory: Path = TAXONOMY_DIR) -> Taxonomy:
    """Missing files give an empty taxonomy (baselines then fall back to node-level matching)."""
    cpath, lpath = directory / "classes.yaml", directory / "node_labels.jsonl"
    raw = yaml.safe_load(cpath.read_text(encoding="utf-8")) if cpath.exists() else None
    raw = raw or {}
    classes = {}
    for c in raw.get("classes") or []:
        tc = TaxonClass(
            id=str(c["id"]),
            kind=c.get("kind", "both"),
            label=c.get("label", str(c["id"])),
            synonyms=tuple(c.get("synonyms") or ()),
            description=c.get("description") or "",
        )
        classes[tc.id] = tc
    labels = []
    if lpath.exists():
        for line in lpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                labels.append(NodeLabel(**json.loads(line)))
    return Taxonomy(classes=classes, labels=tuple(labels), version=str(raw.get("version", "0")))


def save_taxonomy(tax: Taxonomy, directory: Path = TAXONOMY_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    classes = [{**asdict(c), "synonyms": list(c.synonyms)} for c in tax.classes.values()]
    doc = {"version": tax.version, "classes": classes}
    head = "# Built offline by `mise run taxonomy:build`; format: src/camoreasoning/taxonomy.py\n"
    (directory / "classes.yaml").write_text(head + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    lines = (json.dumps(asdict(lb), ensure_ascii=False) for lb in tax.labels)
    (directory / "node_labels.jsonl").write_text("".join(f"{x}\n" for x in lines), encoding="utf-8")


def validate_taxonomy(tax: Taxonomy, node_ids: set[str] | None = None) -> list[str]:
    errs = [f"class {c.id}: bad kind {c.kind!r}" for c in tax.classes.values() if c.kind not in KINDS]
    for lb in tax.labels:
        if lb.class_id not in tax.classes:
            errs.append(f"label {lb.node_id}: unknown class {lb.class_id}")
        if lb.polarity not in POLARITIES:
            errs.append(f"label {lb.node_id}: bad polarity {lb.polarity}")
        if node_ids is not None and lb.node_id not in node_ids:
            errs.append(f"label: unknown node {lb.node_id}")
    return errs
