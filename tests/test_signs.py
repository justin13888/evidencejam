"""The schema's own worked examples for variable-level sign composition."""

import pytest

from camoreasoning.signs import is_null_finding, qualifier_sign, variable_level_sign


@pytest.mark.parametrize(
    "sq,pred,oq,expected",
    [
        ("increased", "prevents", None, -1),
        ("decreased", "causes", None, -1),
        ("decreased", "causes", "decreased", 1),
        ("removed", "disrupts", "increased", 1),
        ("occurred", "causes", "decreased", -1),
        ("present", "associated_with", "increased", None),
        ("unchanged", "causes", "increased", None),
    ],
)
def test_worked_examples(sq, pred, oq, expected):
    edge = {"predicate": pred, "negated": False}
    assert variable_level_sign(edge, {"state_or_change_qualifier": sq}, {"state_or_change_qualifier": oq}) == expected


def test_nulls_and_defaults():
    assert variable_level_sign({"predicate": "causes", "negated": True}, {}, {}) is None
    assert is_null_finding({"causal_language": "no_relationship"})
    assert qualifier_sign(None) == qualifier_sign("ongoing") == 1 and qualifier_sign("unchanged") is None


def test_graph_respects_null_invariant(graph):
    bad = [
        e["id"]
        for e in graph.edges.values()
        if bool(e.get("negated")) != (e.get("causal_language") == "no_relationship")
    ]
    assert not bad, f"{len(bad)} edges break negated <=> no_relationship"
