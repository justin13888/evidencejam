"""End-to-end: run_file writes a valid answers.json with every id, 0 LLM calls when unconfigured."""

import json

import yaml

from camoreasoning.answers import load_questions, validate_answers, validate_entry
from camoreasoning.config import ROOT, Settings
from camoreasoning.contracts import Answer, GoldItem
from camoreasoning.evaluate import score
from camoreasoning.pipeline import Pipeline, run_file


def test_run_file_practice_questions(tmp_path, graph):
    out = tmp_path / "answers.json"
    summary = run_file(ROOT / "questions.yaml", out, Settings())
    doc = json.loads(out.read_text())
    qids = [q.id for q in load_questions(ROOT / "questions.yaml")]
    res = validate_answers(doc, set(graph.edges), qids)
    assert not res["errors"] and summary["calls"] == 0
    assert all((ROOT / p).exists() for a in doc["answers"] for p in a.get("extras", []))
    assert (tmp_path / "outputs" / "footprint.json").exists()


def test_pipeline_answers_something_with_fixture_taxonomy(make_ctx, questions):
    answers, traces = Pipeline(make_ctx()).run(questions)
    assert len(answers) == len(questions)
    assert any(a.status == "answered" for a in answers), "fixture taxonomy should yield answered questions"
    for a in answers:
        assert not validate_entry(a.to_json(), set(make_ctx().graph.edges)), a


def test_load_questions_variants(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(
        yaml.safe_dump([{"id": 7, "question": "a"}, {"question": "b", "extra": 1}, "c", {"id": "", "text": "d"}])
    )
    qs = load_questions(p)
    assert [q.id for q in qs] == ["7", "Q-002", "Q-003", "Q-004"] and [q.text for q in qs] == list("abcd")
    p.write_text(json.dumps({"questions": [{"id": "H-1", "question": "x"}]}))
    assert load_questions(p)[0].id == "H-1"


def test_validator_rejects_bad_entries(graph):
    edges = set(graph.edges)
    good = Answer("a", "no_evidence", "none", 0.9, searched_for="x").to_json()
    assert not validate_entry(good, edges)
    assert validate_entry({**good, "confidence": 1.5}, edges)
    assert validate_entry({**good, "status": "answered"}, edges)
    assert validate_entry({**good, "edge_ids": ["camo:edge_nope"]}, edges)
    assert validate_entry({**good, "searched_for": None}, edges)


def test_score_counts_missing_as_wrong_at_full_confidence():
    gold = [GoldItem("a", "q", "no_evidence"), GoldItem("b", "q", "answered", "increase")]
    res = score(gold, [Answer("a", "no_evidence", "x", 0.8, searched_for="s")])
    assert res["accuracy"] == 0.5 and res["missing"] == 1 and res["calibration"]["brier"] is not None
