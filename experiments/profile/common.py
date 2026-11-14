"""Shared helpers for the item-1 graph profile scripts (vocab.py, traps.py). Read-only over the graph."""

from __future__ import annotations

import json
import re
from pathlib import Path

from camoreasoning.config import RESULTS_DIR
from camoreasoning.graph import Graph

CURIE = re.compile(r"^(wd|ENVO|PATO|CHEBI|GO|NCBITaxon|UBERON|PO):\S+$")
SIGNED_QUALIFIERS = {"increased", "decreased", "present", "absent", "introduced", "removed",
                     "initiated", "terminated", "interrupted", "aborted"}  # fmt: skip
NEGATIVE_QUALIFIERS = {"decreased", "absent", "removed", "terminated", "interrupted", "aborted"}


def _embedding_fields(node: dict) -> dict[str, str]:
    """Parse `embedding_text` ("Name | entity: x (CURIE) | attribute: y | ...") into {field: label}."""
    out: dict[str, str] = {}
    for part in (node.get("embedding_text") or "").split(" | ")[1:]:
        k, _, v = part.partition(": ")
        if k and v:
            out[k.strip()] = re.sub(r"\s*\([A-Za-z]+:[^)]*\)\s*$", "", v.strip())
    return out


def label(node: dict, field: str) -> str | None:
    """Readable label for `entity_term` or `measured_attribute`; CURIEs resolved via embedding_text."""
    raw = node.get(field)
    if not raw:
        return None
    if CURIE.match(str(raw)):
        key = "entity" if field == "entity_term" else "attribute"
        return (_embedding_fields(node).get(key) or str(raw)).lower()
    return str(raw).strip().lower()


def concept(node: dict) -> str:
    """Concept key used to group nodes across papers: entity label + attribute label (if different)."""
    ent, attr = label(node, "entity_term") or node.get("name", "?").lower(), label(node, "measured_attribute")
    return ent if not attr or attr == ent else f"{ent} :: {attr}"


def docs_of(g: Graph, edge_ids) -> set[str]:
    return {g.edges[e].get("source_document") for e in edge_ids}


def example(g: Graph, eid: str, sentence_chars: int = 220) -> dict:
    """Compact, human-checkable view of one edge."""
    e, s, o = g.edges[eid], g.subject(eid), g.object(eid)
    sent = e.get("original_sentence") or ""
    return {
        "edge": eid,
        "doc": e.get("source_document"),
        "subject": f"[{s.get('state_or_change_qualifier')}] {s.get('name')}",
        "predicate": ("NOT " if e.get("negated") else "") + str(e.get("predicate")),
        "object": f"[{o.get('state_or_change_qualifier')}] {o.get('name')}",
        "causal_language": e.get("causal_language"),
        "grade": e.get("certainty_grade"),
        "sentence": sent if len(sent) <= sentence_chars else sent[: sentence_chars - 1] + "…",
    }


def write_json(name: str, obj) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    return path
