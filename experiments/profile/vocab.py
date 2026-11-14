"""ROADMAP item 1: dump the cause (edge subject) and outcome (edge object) vocabulary of the graph.

    python experiments/profile/vocab.py

Writes experiments/results/vocab_causes.tsv, vocab_outcomes.tsv and vocab_summary.json. Nodes are
grouped into concepts by readable entity label + attribute label (CURIEs resolved through
`embedding_text`), so the counts show how much merging the taxonomy (item 3) has to do. Deterministic.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict

from common import concept, docs_of, label, write_json

from camoreasoning.config import RESULTS_DIR
from camoreasoning.graph import load_graph
from camoreasoning.signs import is_null_finding

TOP = 60


def side_table(g, side: str) -> list[dict]:
    groups: dict[str, dict] = defaultdict(lambda: {"edges": [], "nodes": set(), "types": Counter(), "quals": Counter()})
    for eid, e in g.edges.items():
        n = g.nodes[e[side]]
        row = groups[concept(n)]
        row["edges"].append(eid)
        row["nodes"].add(n["id"])
        row["types"][str(n.get("entity_type"))] += 1
        row["quals"][str(n.get("state_or_change_qualifier"))] += 1
    rows = []
    for key, r in groups.items():
        nodes = sorted(r["nodes"])
        rows.append({
            "concept": key,
            "entity_type": ",".join(t for t, _ in r["types"].most_common()),
            "edges": len(r["edges"]),
            "documents": len(docs_of(g, r["edges"])),
            "null_edges": sum(is_null_finding(g.edges[x]) for x in r["edges"]),
            "nodes": len(nodes),
            "qualifiers": " ".join(f"{q}:{c}" for q, c in sorted(r["quals"].items(), key=lambda kv: (-kv[1], kv[0]))),
            "example_names": " || ".join(sorted({g.nodes[x]["name"] for x in nodes})[:3]),
            "example_node_ids": " ".join(nodes[:3]),
        })  # fmt: skip
    rows.sort(key=lambda r: (-r["documents"], -r["edges"], r["concept"]))
    return rows


def write_tsv(name: str, rows: list[dict]) -> None:
    with open(RESULTS_DIR / name, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def field_vocab(g, side: str, field: str) -> dict[str, int]:
    """Edge counts per readable `field` label on one side of the edge."""
    c = Counter(label(g.nodes[e[side]], field) or "(none)" for e in g.edges.values())
    return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP])


def applied_to_vocab(g) -> dict[str, int]:
    c: Counter = Counter()
    for n in g.nodes.values():
        for a in n.get("applied_to") or []:
            c[str(a.get("entity_term"))] += 1
    return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP])


def summarize(rows: list[dict]) -> dict:
    by_type: Counter = Counter()
    for r in rows:
        by_type[r["entity_type"].split(",")[0]] += 1
    return {
        "concepts": len(rows),
        "concepts_in_>=2_documents": sum(r["documents"] >= 2 for r in rows),
        "concepts_in_>=3_documents": sum(r["documents"] >= 3 for r in rows),
        "concepts_in_>=5_documents": sum(r["documents"] >= 5 for r in rows),
        "edges_on_concepts_in_>=2_documents": sum(r["edges"] for r in rows if r["documents"] >= 2),
        "concepts_by_main_entity_type": dict(by_type.most_common()),
        "top_by_documents": [
            {k: r[k] for k in ("concept", "entity_type", "documents", "edges", "null_edges")} for r in rows[:TOP]
        ],
    }


def main() -> None:
    g = load_graph()
    causes, outcomes = side_table(g, "subject"), side_table(g, "object")
    assert sum(r["edges"] for r in causes) == len(g.edges) == sum(r["edges"] for r in outcomes)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    write_tsv("vocab_causes.tsv", causes)
    write_tsv("vocab_outcomes.tsv", outcomes)
    interventions = [r for r in causes if r["entity_type"].startswith("management_intervention")]
    conditions = [r for r in causes if not r["entity_type"].startswith("management_intervention")]
    summary = {
        "how": "nodes grouped by readable entity_term label + measured_attribute label; counts are edges/documents",
        "causes": summarize(causes),
        "outcomes": summarize(outcomes),
        "cause_interventions": {
            "concepts": len(interventions),
            "edges": sum(r["edges"] for r in interventions),
            "top": [{k: r[k] for k in ("concept", "documents", "edges")} for r in interventions[:TOP]],
        },
        "cause_conditions": {
            "concepts": len(conditions),
            "edges": sum(r["edges"] for r in conditions),
            "top": [{k: r[k] for k in ("concept", "entity_type", "documents", "edges")} for r in conditions[:TOP]],
        },
        "subject_entity_terms": field_vocab(g, "subject", "entity_term"),
        "object_entity_terms": field_vocab(g, "object", "entity_term"),
        "subject_measured_attributes": field_vocab(g, "subject", "measured_attribute"),
        "object_measured_attributes": field_vocab(g, "object", "measured_attribute"),
        "applied_to_terms_by_node": applied_to_vocab(g),
    }
    path = write_json("vocab_summary.json", summary)
    print(f"causes: {len(causes)} concepts, outcomes: {len(outcomes)} concepts -> {path.parent}")


if __name__ == "__main__":
    main()
