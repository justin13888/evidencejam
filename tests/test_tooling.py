"""Offline tooling: annotate harness (strict check, merge, review), eval stage metrics, calibrate, settings."""

from __future__ import annotations

import csv
import json

import pytest
import yaml

from camoreasoning import annotate as A
from camoreasoning import registry
from camoreasoning.config import ROOT, Settings, load_settings
from camoreasoning.contracts import DevQuestion, GoldItem
from camoreasoning.evaluate import load_devsets, run_calibrate, run_eval, save_devset, scorecard

FIXTURE_DEVSET = ROOT / "tests" / "fixtures" / "devset" / "gold_fixture.yaml"
FIXTURE_TAX = ROOT / "tests" / "fixtures" / "taxonomy"
E1 = {"ref": "e1", "effect": 1}


@pytest.fixture
def tmp_annotate(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ANNOTATE_DIR", tmp_path / "annotate")
    monkeypatch.setattr(A, "DEVSETS_DIR", tmp_path / "devsets")
    return tmp_path


def _write_out(task, name, rows):
    A._write_jsonl(A.task_dir(task) / "out" / f"{name}.jsonl", rows)


def test_gold_task_strict_check_merge_and_review(tmp_annotate, make_ctx):
    ctx = make_ctx()
    seed = next(iter(ctx.graph.edges))
    qs = [DevQuestion("D-1", "What effect does mulch have on seedling survival?", ("t",), "dev", {"seed_edge": seed}),
          DevQuestion("D-2", "What effect does mowing have on soil carbon?", (), "dev", {})]  # fmt: skip
    save_devset(tmp_annotate / "devsets" / "generated.yaml", qs)
    res = A.export("gold", ctx, chunk=10)
    assert res["items"] == 2 and res["chunks"] == 1
    items = A._read_jsonl(A.task_dir("gold") / "in" / "0001.jsonl")
    assert "_meta" not in items[0] and items[0]["candidates"][0]["ref"] == "e1"
    assert "camo:edge" not in json.dumps(items), "real edge ids must stay hidden from the labeller"
    assert A.check("gold")["redo"] == ["0001"]  # not labelled yet

    bad = [
        {"id": "D-1", "status": "answered", "direction": "up", "certainty": "low", "edges": [E1]},
        {"id": "D-1", "status": "answered", "direction": "increase", "certainty": "low", "edges": []},
        {"id": "D-9", "status": "no_evidence", "direction": None, "certainty": None, "edges": []},
    ]  # fmt: skip
    _write_out("gold", "0001", bad)
    errs = " | ".join(A.check("gold")["errors"]["0001"])
    assert "duplicate" in errs and "unknown id" in errs and "D-2: no label" in errs

    _write_out("gold", "0001", [
        {"id": "D-1", "status": "answered", "direction": "increase", "certainty": "high",
         "edges": [{"ref": "e999", "effect": 1}]},
        {"id": "D-2", "status": "no_evidence", "direction": "increase", "certainty": None, "edges": [], "x": 1},
    ])  # fmt: skip
    errs = " | ".join(A.check("gold")["errors"]["0001"])
    assert "e999" in errs and "extra keys" in errs

    _write_out("gold", "0001", [
        {"id": "D-1", "status": "answered", "direction": "increase", "certainty": "low", "edges": [E1]},
        {"id": "D-2", "status": "no_evidence", "direction": None, "certainty": None, "edges": [], "note": "ok"},
    ])  # fmt: skip
    assert not A.check("gold")["redo"]
    assert A.merge("gold")["merged"] == 2
    gold = registry.get("gold_labeler", "annotated").label(qs, ctx)
    g1 = next(g for g in gold if g.id == "D-1")
    assert g1.edge_ids == (seed,) and g1.edge_effects == ((seed, 1),) and "answerable" in g1.tags

    path = tmp_annotate / "review.csv"
    assert A.review_export("gold", path, n=5)["rows"] == 2
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["ok"] = "y" if r["id"] == "D-2" else "n"
        if r["id"] == "D-1":
            r["human_direction"], r["reviewer"] = "decrease", "jc"
            r["human_edges"] = "e1:-1"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    res = A.review_import("gold", path)
    assert res["agreement"] == 0.5 and res["fields_corrected"]["direction"] == 1
    A.merge("gold")
    g1 = next(g for g in registry.get("gold_labeler", "annotated").label(qs, ctx) if g.id == "D-1")
    assert g1.direction == "decrease" and g1.edge_effects == ((seed, -1),) and g1.source == "human:jc"


def test_node_label_and_question_tasks_export(tmp_annotate, make_ctx):
    ctx = make_ctx()
    assert A.export("node_labels", ctx, chunk=3, n=5)["chunks"] == 2
    item = A._read_jsonl(A.task_dir("node_labels") / "in" / "0001.jsonl")[0]
    _write_out("node_labels", "0001", [{"id": item["id"], "labels": [{"class": "nope", "polarity": 1}]}])
    assert "nope" in " ".join(A.check("node_labels", "1")["errors"]["0001"])
    res = A.export("questions", ctx, chunk=50, n=24)
    assert res["items"] == 24
    rows = A._read_jsonl(A.task_dir("questions") / "in" / "0001.jsonl")
    assert {r["kind"] for r in rows} == {"edge", "pair"}
    _write_out(
        "questions", "0001", [{"id": r["id"], "cause": "mulch", "outcome": f"thing {i}"} for i, r in enumerate(rows)]
    )
    assert A.merge("questions")["merged"] == 24
    qs = registry.get("devset_builder", "annotated").build(ctx.taxonomy, ctx)
    assert len(qs) == 24 and qs[0].question.startswith("What effect does mulch have on")
    assert any(t.startswith("trap:") for q in qs for t in q.tags)


def test_gold_labeler_guard_blocks_taxonomy_reads():
    import inspect

    for name in registry.names("gold_labeler"):
        src = inspect.getsource(inspect.getmodule(type(registry.get("gold_labeler", name))))
        code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith(("#", '"')))
        assert "ctx.taxonomy" not in code and "node_labels" not in code, name


def test_edge_effects_round_trip(tmp_path):
    g = GoldItem("a", "q", "answered", "increase", "low", ("e1", "e2"), ("t",), "dev", "x", (("e1", 1), ("e2", None)))
    save_devset(tmp_path / "d.yaml", [g])
    assert load_devsets([tmp_path / "d.yaml"]) == [g]


def test_eval_scorecard_and_oracle_on_fixture():
    s = Settings(taxonomy_dir=FIXTURE_TAX)
    res = run_eval(s, None, 1, [FIXTURE_DEVSET])
    assert res["n"] == 9 and res["oracle"]["n"] >= 1 and res["retrieval_recall"] is not None
    card = scorecard(res)
    assert set(card) >= {"A taxonomy+linking", "B engine", "C calibration", "D energy+release"}
    json.dumps(card)


def test_calibrate_default_has_nothing_to_fit():
    res = run_calibrate(Settings(taxonomy_dir=FIXTURE_TAX), "dev", [FIXTURE_DEVSET])
    assert res["n"] > 0 and "nothing to fit" in res["note"]
    with pytest.raises(SystemExit):
        run_calibrate(Settings(), "holdout", [FIXTURE_DEVSET])


def test_taxonomy_dir_env():
    s = load_settings({"CAMOREASONING_TAXONOMY_DIR": "tests/fixtures/taxonomy"})
    assert s.taxonomy_dir == FIXTURE_TAX
    from camoreasoning.pipeline import make_context

    assert not make_context(s).taxonomy.empty


def test_fixture_devset_is_marked_smoke_only():
    head = FIXTURE_DEVSET.read_text(encoding="utf-8").splitlines()[0]
    assert "SMOKE FIXTURE ONLY" in head and yaml.safe_load(FIXTURE_DEVSET.read_text())["items"]


def test_eval_scores_each_devset_file(tmp_path):
    """#50: two devset files get one score each, next to the pooled score."""
    items = yaml.safe_load(FIXTURE_DEVSET.read_text())["items"]
    half = len(items) // 2
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text(yaml.safe_dump({"items": items[:half]}))
    b.write_text(yaml.safe_dump({"items": items[half:]}))
    res = run_eval(Settings(taxonomy_dir=FIXTURE_TAX), None, 1, [a, b])
    by = res["by_file"]
    assert set(by) == {"a.yaml", "b.yaml"} and by["a.yaml"]["n"] + by["b.yaml"]["n"] == res["n"]
    card = scorecard(res)
    assert set(card["by_file"]) == {"a.yaml", "b.yaml"} and "D energy+release" not in card["by_file"]["a.yaml"]
    assert "by_file" not in run_eval(Settings(taxonomy_dir=FIXTURE_TAX), None, 1, [a])


def test_strategy_overrides_reject_unknown_stages():
    """#51: a typo'd or padded stage key used to be ignored silently, so eval scored the default."""
    assert load_settings({}, strategies={" grader": "rubric "}).strategies == {"grader": "rubric"}
    assert load_settings({"CAMOREASONING_STRATEGY_GRADER": "rubric"}).strategies == {"grader": "rubric"}
    with pytest.raises(ValueError, match="unknown stage 'bogus'"):
        load_settings({}, strategies={"bogus": "x"})
    with pytest.raises(ValueError, match="unknown stage 'GRADR'"):
        load_settings({"CAMOREASONING_STRATEGY_GRADR": "rubric"})


@pytest.mark.parametrize("argv", [["-s", "bogus=x"], ["-s", "grader"], ["-s", "grader=rubric -s linker=phrase"],
                                  ["-s", "grader=nope"]])  # fmt: skip
def test_cli_rejects_bad_strategy_overrides(argv, capsys):
    from camoreasoning.cli import main

    with pytest.raises(SystemExit) as exc:
        main([*argv, "strategies"])
    assert exc.value.code == 2 and "error:" in capsys.readouterr().err


def test_cli_accepts_padded_override(capsys):
    from camoreasoning.cli import main

    assert main(["-s", " grader=rubric", "strategies"]) == 0
