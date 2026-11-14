"""D4 rubric grader on hand-built verdicts that point at real graph edges."""

from __future__ import annotations

import pytest

from camoreasoning.contracts import EdgeVote, Verdict
from camoreasoning.registry import get
from camoreasoning.strategies.grader import rubric

OBS = {"observational_cross_sectional", "observational_longitudinal"}


def _designs(e: dict) -> set[str]:
    return set((e.get("evidential_basis") or {}).get("evidence_types") or ())


def _find(graph, n: int = 1, **want) -> list[str]:
    """First n edge ids matching predicate / grade / negated / design predicates."""
    hits = []
    for eid, e in graph.edges.items():
        if want.get("predicate") and e.get("predicate") != want["predicate"]:
            continue
        if want.get("grade") and e.get("certainty_grade") != want["grade"]:
            continue
        if "negated" in want and bool(e.get("negated")) != want["negated"]:
            continue
        if "observational" in want and (bool(_designs(e)) and _designs(e) <= OBS) != want["observational"]:
            continue
        hits.append(eid)
        if len(hits) == n:
            return hits
    pytest.skip(f"graph has no edge matching {want}")


def vote(graph, eid: str, *, effect: int | None = 1, reason: str = "signed", grade: str | None = "keep") -> EdgeVote:
    e = graph.edges.get(eid, {})
    return EdgeVote(
        edge_id=eid,
        doc_id=e.get("source_document", "doc:x"),
        effect=effect,
        included=True,
        reason=reason,
        certainty_grade=e.get("certainty_grade") if grade == "keep" else grade,
        causal_language=e.get("causal_language"),
    )


def verdict(*votes: EdgeVote, direction: str = "increase") -> Verdict:
    return Verdict(status="answered", direction=direction, votes=tuple(votes))


@pytest.fixture
def ctx(make_ctx):
    return make_ctx()


@pytest.fixture
def grade(ctx):
    g = get("grader", "rubric")
    return lambda v: g.grade(v, ctx)


@pytest.fixture
def ids(graph):
    return {
        "causes_mod": _find(graph, 3, predicate="causes", grade="moderate", negated=False),
        "causes_low": _find(graph, 2, predicate="causes", grade="low", negated=False),
        "causes_vlow": _find(graph, 1, predicate="causes", grade="very_low", negated=False),
        "null_mod": _find(graph, 1, predicate="causes", grade="moderate", negated=True),
        "assoc_low": _find(graph, 1, predicate="associated_with", grade="low"),
        "assoc_mod": _find(graph, 1, predicate="associated_with", grade="moderate"),
        "corr_low": _find(graph, 1, predicate="correlated_with", grade="low"),
    }


def test_no_evidence_is_none(grade):
    assert grade(Verdict(status="no_evidence", direction=None, votes=())) is None


def test_lower_median(graph, grade, ids):
    m, lo, vl = ids["causes_mod"], ids["causes_low"], ids["causes_vlow"]
    assert grade(verdict(vote(graph, m[0]))) == "moderate"
    assert grade(verdict(vote(graph, m[0]), vote(graph, m[1]), vote(graph, lo[0]))) == "moderate"
    assert grade(verdict(vote(graph, m[0]), vote(graph, lo[0]))) == "low"  # lower median of 2
    assert grade(verdict(vote(graph, m[0]), vote(graph, lo[0]), vote(graph, vl[0]))) == "low"


def test_excluded_votes_ignored(graph, grade, ids):
    excluded = EdgeVote(ids["assoc_low"][0], "d", None, False, "non_directional_predicate", "very_low")
    assert grade(verdict(vote(graph, ids["causes_mod"][0]), excluded)) == "moderate"


def test_mixed_drops_one(graph, grade, ids):
    m = ids["causes_mod"]
    assert grade(verdict(vote(graph, m[0]), vote(graph, m[1], effect=-1), direction="mixed")) == "low"


def test_all_associational_drops_one(graph, grade, ids):
    assert grade(verdict(vote(graph, ids["assoc_mod"][0]))) == "low"
    assert grade(verdict(vote(graph, ids["assoc_low"][0]), vote(graph, ids["corr_low"][0]))) == "very_low"


def test_associational_reason_tag_counts(graph, grade, ids):
    assert grade(verdict(vote(graph, ids["causes_mod"][0], reason="associational"))) == "low"


def test_partly_associational_no_drop(graph, grade, ids):
    v = verdict(vote(graph, ids["causes_mod"][0]), vote(graph, ids["assoc_mod"][0]))
    assert grade(v) == "moderate"


def test_null_on_negated_causes_not_associational(graph, grade, ids):
    assert grade(verdict(vote(graph, ids["null_mod"][0], effect=0, reason="null"), direction="no_effect")) == "moderate"


def test_mixed_and_associational_single_drop(graph, grade, ids):
    a = ids["assoc_mod"][0]
    assert grade(verdict(vote(graph, a), vote(graph, a, effect=-1), direction="mixed")) == "low"


def test_floor_very_low(graph, grade, ids):
    vl = ids["causes_vlow"][0]
    assert grade(verdict(vote(graph, vl), vote(graph, vl, effect=-1), direction="mixed")) == "very_low"


def test_never_high(graph, grade, ids):
    m = ids["causes_mod"]
    assert grade(verdict(vote(graph, m[0], grade="high"))) == "moderate"
    assert grade(verdict(vote(graph, m[0], grade="high"), vote(graph, m[1], grade="high"))) == "moderate"
    # high with a drop lands on moderate, not below
    assert grade(verdict(vote(graph, ids["assoc_mod"][0], grade="high"))) == "moderate"


def test_missing_grades_low(graph, grade, ids):
    assert grade(verdict(vote(graph, ids["causes_mod"][0], grade=None))) == "low"
    assert grade(verdict(vote(graph, ids["causes_mod"][0], grade="bogus"))) == "low"


def test_unknown_edge_id_is_safe(grade):
    v = EdgeVote("camo:edge_missing", "", 1, True, "signed", "moderate")
    assert grade(verdict(v)) == "moderate"


def test_observational_single_study_flag(graph, grade, monkeypatch):
    obs = _find(graph, 1, predicate="causes", grade="moderate", negated=False, observational=True)[0]
    rct = _find(graph, 1, predicate="causes", grade="moderate", negated=False, observational=False)[0]
    assert rubric.OBSERVATIONAL_SINGLE_STUDY_DROP is False
    assert grade(verdict(vote(graph, obs))) == "moderate"
    monkeypatch.setattr(rubric, "OBSERVATIONAL_SINGLE_STUDY_DROP", True)
    assert grade(verdict(vote(graph, obs))) == "low"
    assert grade(verdict(vote(graph, rct))) == "moderate"
    # still one level at most when mixed as well
    assert grade(verdict(vote(graph, obs), vote(graph, obs, effect=-1), direction="mixed")) == "low"
    # two documents: no observational drop
    other = next(
        eid
        for eid, e in graph.edges.items()
        if e.get("source_document") != graph.edges[obs].get("source_document")
        and e.get("predicate") == "causes"
        and e.get("certainty_grade") == "moderate"
        and not e.get("negated")
        and _designs(e) <= OBS
        and _designs(e)
    )
    assert grade(verdict(vote(graph, obs), vote(graph, other))) == "moderate"


def test_deterministic(graph, grade, ids):
    v = verdict(vote(graph, ids["causes_mod"][0]), vote(graph, ids["assoc_low"][0]))
    assert grade(v) == grade(v)
