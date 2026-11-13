"""Paths we cannot replicate exactly on judging day, battle-tested: LLM faults, hostile inputs, scale,
the shell entry points. Rule under test: answers.json is always valid and has every question id."""

from __future__ import annotations

import json
import os
import subprocess
import time

import pytest
import yaml

from camoreasoning.answers import load_questions, validate_answers
from camoreasoning.components import ClassLinker
from camoreasoning.config import ROOT, Settings
from camoreasoning.llm import LLM, LLMError
from camoreasoning.pipeline import Pipeline, ask, run_file
from camoreasoning.registry import get
from tests.robustness.fake_llm import MODES, FakeLLM

pytestmark = pytest.mark.robust


def settings_for(fake: FakeLLM, **kw) -> Settings:
    return Settings(llm_url=fake.url, llm_model="fake", llm_key="k", llm_timeout=1.0, **kw)


class ProbeLinker(ClassLinker):
    """Stands in for any LLM linker: one batched call, then baseline linking; raises on missing ids."""

    def link(self, batch, ctx):
        got = ctx.llm.batch_json("map", [{"id": p.question.id, "q": p.question.text} for p in batch])
        if len(got) < len(batch):
            raise LLMError("missing ids")
        return get("linker", "baseline").link(batch, ctx)


@pytest.mark.parametrize("mode", MODES)
def test_llm_client_only_raises_llmerror(mode):
    fake = FakeLLM(mode)
    try:
        llm = LLM(settings_for(fake))
        try:
            out = llm.batch_json("sys", [{"id": "a"}, {"id": "b"}])
            assert isinstance(out, dict)
        except LLMError:
            pass
        assert llm.meter.calls <= 2
        if mode == "http400_extras":
            assert "chat_template_kwargs" not in fake.requests[-1]
    finally:
        fake.close()


@pytest.mark.parametrize("mode", MODES)
def test_pipeline_survives_every_llm_mode(mode, make_ctx, questions):
    fake = FakeLLM(mode)
    try:
        ctx = make_ctx(settings_for(fake))
        p = Pipeline(ctx)
        p.s["linker"] = ProbeLinker()
        answers, _ = p.run(questions)
        doc = {"team": "t", "answers": [a.to_json() for a in answers]}
        res = validate_answers(doc, set(ctx.graph.edges), [q.id for q in questions])
        assert not res["errors"], res["errors"][:5]
        if mode in ("ok", "fenced", "think"):
            assert ctx.llm.meter.calls == -(-len(questions) // 25), "one batched call per 25 questions"
    finally:
        fake.close()


def test_budget_guard_stops_calls():
    fake = FakeLLM("ok")
    try:
        llm = LLM(settings_for(fake, max_calls=1))
        out = llm.batch_json("sys", [{"id": str(i)} for i in range(60)], chunk=25)
        assert llm.meter.calls == 1 and len(out) == 25
    finally:
        fake.close()


@pytest.mark.parametrize(
    "content",
    [
        "",
        "questions: []\n",
        "questions:\n  - id: H-1\n    question: What effect does fire have on biomass?\n"
        "  - id: H-1\n    question: dup\n",
        'questions:\n  - {id: 3, question: null}\n  - {question: "What effect does “mulch” have on richness?"}\n',
        "questions: [unclosed\n",
        "- What effect does fertilization have on seedling survival?\n",
    ],
)
def test_hostile_question_files(content, tmp_path):
    q, out = tmp_path / "q.yaml", tmp_path / "answers.json"
    q.write_text(content, encoding="utf-8")
    run_file(q, out, Settings())
    doc = json.loads(out.read_text())
    try:
        qids = [x.id for x in load_questions(q)]
    except yaml.YAMLError:
        qids = []
    from camoreasoning.graph import load_graph

    assert not validate_answers(doc, set(load_graph().edges), qids)["errors"]


def test_500_questions_under_60s(tmp_path, taxonomy):
    pairs = [(c.label, o.label) for c in taxonomy.of_kind("cause") for o in taxonomy.of_kind("outcome")]
    qs = [{"id": f"H-{i:03d}", "question": f"What effect does {pairs[i % len(pairs)][0]} have on thing {i}?"}
          for i in range(500)]  # fmt: skip
    q = tmp_path / "q.yaml"
    q.write_text(yaml.safe_dump({"questions": qs}))
    t0 = time.perf_counter()
    run_file(q, tmp_path / "answers.json", Settings())
    assert time.perf_counter() - t0 < 60


def test_ask_never_crashes_on_practice_questions(tmp_path):
    for q in load_questions(ROOT / "questions.yaml"):
        out = ask(q.text, Settings(), out_dir=tmp_path)
        assert out["status"] in ("answered", "no_evidence") and out["answer"]


def test_run_sh_with_unreachable_llm_and_relative_paths(tmp_path):
    env = {**os.environ, "BRINE_URL": "http://127.0.0.1:9/v1", "BRINE_MODEL": "x", "BRINE_API_KEY": "x",
           "CAMOREASONING_LLM_TIMEOUT": "2"}  # fmt: skip
    (tmp_path / "q.yaml").write_text((ROOT / "questions.yaml").read_text())
    subprocess.run([str(ROOT / "run.sh"), "q.yaml", "sub/answers.json"], cwd=tmp_path, env=env, check=True,
                   capture_output=True, timeout=300)  # fmt: skip
    doc = json.loads((tmp_path / "sub" / "answers.json").read_text())
    assert len(doc["answers"]) == len(load_questions(ROOT / "questions.yaml"))
