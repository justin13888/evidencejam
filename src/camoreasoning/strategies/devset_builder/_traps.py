"""Trap tags keyed like experiments/results/trap_inventory.json (`trap:<key>`), from graph fields only.

The annotate harness writes 8 short hint tags per seed edge (`trap:null`, ...). Per-tag eval (ROADMAP item 7)
needs the inventory keys, so short tags are renamed here and the keys the harness does not compute are derived
from the seed edge with the same criteria as experiments/profile/traps.py. Never reads the taxonomy (D5).
"""

from __future__ import annotations

import re
from collections import defaultdict

from camoreasoning.signs import predicate_sign

RENAME = {
    "trap:null": "trap:null_is_not_decrease",
    "trap:twin": "trap:twin_edges_one_sentence",
    "trap:associational": "trap:associational_is_not_causal",
    "trap:reversed": "trap:reversed_edges",
    "trap:removed_subject": "trap:negative_subject_qualifiers",
    "trap:unchanged": "trap:unchanged_is_not_null",
    "trap:moderator": "trap:moderators_mediators",
    "trap:sign_flip": None,  # superseded by the inventory keys below (double negation, negative subject)
}
NEGATIVE_QUALIFIERS = {"decreased", "absent", "removed", "terminated", "interrupted", "aborted"}
TIME = re.compile(r"\b(time|year|age|duration)\b")
CURIE = re.compile(r"^[A-Za-z][\w.-]*:\S+$")


def _fields(node: dict) -> dict[str, str]:
    out = {}
    for part in (node.get("embedding_text") or "").split(" | ")[1:]:
        k, _, v = part.partition(": ")
        if v:
            out[k.strip()] = re.sub(r"\s*\([A-Za-z][\w.-]*:[^)]*\)$", "", v).strip().lower()
    return out


def _label(node: dict, field: str) -> str | None:
    raw = node.get(field)
    if not raw:
        return None
    if CURIE.match(str(raw)):
        return _fields(node).get("entity" if field == "entity_term" else "attribute") or str(raw).lower()
    return str(raw).lower()


def concept(node: dict) -> str:
    """Entity label + attribute label, as in experiments/profile/common.py."""
    ent, attr = _label(node, "entity_term") or node.get("name", "?").lower(), _label(node, "measured_attribute")
    return ent if not attr or attr == ent else f"{ent} :: {attr}"


class EdgeTraps:
    """Inventory keys the harness does not tag, per edge."""

    def __init__(self, graph):
        self.g = graph
        per = defaultdict(int)
        for e in graph.edges.values():
            per[self._doc_pair(e)] += 1
        self.many = {k for k, n in per.items() if n > 1}

    def _doc_pair(self, e: dict) -> tuple:
        n = self.g.nodes
        return e.get("source_document"), concept(n[e["subject"]]), concept(n[e["object"]])

    def tags(self, eid: str) -> list[str]:
        e = self.g.edges.get(eid)
        if e is None:
            return []
        s, o = self.g.nodes[e["subject"]], self.g.nodes[e["object"]]
        out = []
        if predicate_sign(e.get("predicate")) == -1 and o.get("state_or_change_qualifier") in NEGATIVE_QUALIFIERS | {
            "unchanged"
        }:
            out.append("trap:negative_predicates_double_negation")
        if {c.get("comparator_type") for c in e.get("comparator") or []} == {"reference_undisturbed"}:
            out.append("trap:comparator_reference")
        if TIME.search(concept(s)):
            out.append("trap:time_as_cause")
        if self._doc_pair(e) in self.many:
            out.append("trap:one_study_many_edges")
        return out


def inventory_tags(hint_tags, seed_edge: str | None, traps: EdgeTraps) -> tuple[str, ...]:
    out = [RENAME.get(t, t) for t in hint_tags or ()]
    out += traps.tags(seed_edge) if seed_edge else []
    return tuple(dict.fromkeys(t for t in out if t))
