"""Graph profiler: field coverage, vocabularies, node reuse and sign-trap counts (ROADMAP: profile)."""

from __future__ import annotations

from collections import Counter

from camoreasoning.graph import Graph
from camoreasoning.signs import is_null_finding, predicate_sign, variable_level_sign


def _coverage(items) -> dict[str, int]:
    c: Counter = Counter()
    for it in items:
        c.update(k for k, v in it.items() if v not in (None, [], {}, ""))
    return dict(c.most_common())


def profile_graph(g: Graph, top: int = 40) -> dict:
    E, N = list(g.edges.values()), g.nodes
    deg: Counter = Counter()
    for e in E:
        deg[e["subject"]] += 1
        deg[e["object"]] += 1
    docs_per_node = Counter()
    for nid in N:
        docs_per_node[nid] = len({g.edges[x].get("source_document") for x in (*g.out_edges.get(nid, ()),
                                                                              *g.in_edges.get(nid, ()))})  # fmt: skip
    naive_vs_var = Counter()
    for e in E:
        p = predicate_sign(e.get("predicate"))
        v = variable_level_sign(e, N[e["subject"]], N[e["object"]])
        if p is not None and v is not None and not is_null_finding(e):
            naive_vs_var["agree" if p == v else "disagree"] += 1
    return {
        "meta": {k: v for k, v in g.meta.items() if k != "order"},
        "counts": {"nodes": len(N), "edges": len(E), "documents": len(g.docs)},
        "coverage": {"nodes": _coverage(N.values()), "edges": _coverage(E), "documents": _coverage(g.docs.values())},
        "edges": {
            f: dict(Counter(str(e.get(f)) for e in E).most_common())
            for f in ("predicate", "causal_language", "certainty_grade", "negated", "ecosystem_context")
        },
        "evidence_types": dict(
            Counter(t for e in E for t in (e.get("evidential_basis") or {}).get("evidence_types", [])).most_common()
        ),  # fmt: skip
        "comparators": dict(
            Counter(c.get("comparator_type") for e in E for c in e.get("comparator") or []).most_common()
        ),
        "nodes": {
            f: dict(Counter(str(n.get(f)) for n in N.values()).most_common(top))
            for f in ("entity_type", "state_or_change_qualifier", "entity_term", "measured_attribute")
        },
        "qualifier_pairs": {
            f"{a}->{b}": n
            for (a, b), n in Counter(
                (N[e["subject"]].get("state_or_change_qualifier"), N[e["object"]].get("state_or_change_qualifier"))
                for e in E
            ).most_common(top)
        },  # fmt: skip
        "node_degree": dict(sorted(Counter(min(d, 10) for d in deg.values()).items())),
        "nodes_in_multiple_documents": sum(1 for v in docs_per_node.values() if v > 1),
        "predicate_sign_vs_variable_level": dict(naive_vs_var),
        "subject_entity_types": dict(Counter(N[e["subject"]].get("entity_type") for e in E).most_common()),
        "object_entity_types": dict(Counter(N[e["object"]].get("entity_type") for e in E).most_common()),
    }
