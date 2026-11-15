"""The ask CLI (ROADMAP item 18): readable card, --json back-compat, refusing unclear questions (exit 2),
loud bugs (traceback, non-zero exit) while the batch run keeps its per-question fallback, and never
crashing or stalling on a dead or faulty LLM."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

import pytest
import yaml

from camoreasoning import pipeline, registry
from camoreasoning.answers import load_questions, validate_answers
from camoreasoning.cli import main
from camoreasoning.components import BASES
from camoreasoning.config import EXPERIMENTS_DIR, ROOT, RUNTIME_STAGES, Settings
from tests.robustness import fake_llm
from tests.robustness.fake_llm import FakeLLM

OFFTEMPLATE = yaml.safe_load((EXPERIMENTS_DIR / "ask" / "offtemplate.yaml").read_text(encoding="utf-8"))
ITEMS, UNCLEAR = OFFTEMPLATE["items"], OFFTEMPLATE["unclear"]
ASK_STRATEGIES = {"parser": "assisted", "linker": "assisted"}  # what ./ask.sh selects
ANSWERED_Q = "Does mulching lead to more invasive plants?"
# Known gaps in llm.py (frozen, other owner); strict xfails so they flip to failures once fixed.
MALFORMED_URL_BUG = "llm.py lets urllib's ValueError escape for a scheme-less BRINE_URL instead of LLMError"
# ask.sh's default LLM timeout; llm.py retries a timed-out call once after 2 s, so a hung endpoint costs 2t + 2 s.
ASK_TIMEOUT = re.search(r"LLM_TIMEOUT:-(\d+(?:\.\d+)?)", (ROOT / "ask.sh").read_text()).group(1)


@pytest.fixture(autouse=True)
def ask_env(monkeypatch, tmp_path):
    """No endpoint unless a test sets one; ask.sh's timeout and strategies; pages under tmp_path."""
    for k in ("BRINE_URL", "BRINE_MODEL", "BRINE_API_KEY", "CAMOREASONING_TAXONOMY_DIR", "CAMOREASONING_LLM_CACHE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CAMOREASONING_LLM_TIMEOUT", ASK_TIMEOUT)
    for stage, name in ASK_STRATEGIES.items():
        monkeypatch.setenv(f"CAMOREASONING_STRATEGY_{stage.upper()}", name)
    monkeypatch.setattr(pipeline.ask_frame, "__defaults__", (None, tmp_path / "outputs"))


def cli(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["ask", *argv])
    return code, out.getvalue()


# --- output -----------------------------------------------------------------------------------------


def test_card_for_answered_question():
    code, out = cli(ANSWERED_Q)
    lines = out.splitlines()
    assert code == 0
    assert lines[0] == f"Q: {ANSWERED_Q}"
    assert lines[1].startswith("Linked: mulch & surface cover -> invasive / non-native species abundance (via ")
    assert lines[2].startswith("Answer: ")
    assert lines[3].startswith("Direction: ") and "Certainty: " in lines[3] and "Confidence: " in lines[3]
    assert lines[4].startswith("Cites: ") and lines[4].endswith(" studies")
    assert any(x.startswith("Evidence page: ") for x in lines)
    assert lines[-1].startswith("(") and "LLM calls" in lines[-1] and lines[-1].endswith(" tokens)")


def test_json_flag_prints_the_ask_entry():
    code, out = cli("--json", ANSWERED_Q)
    entry = json.loads(out)
    assert code == 0
    assert set(entry) == set(pipeline.ask(ANSWERED_Q, Settings(strategies=ASK_STRATEGIES)))
    assert entry["id"] == "ASK" and entry["status"] in ("answered", "no_evidence") and "footprint" in entry


@pytest.mark.parametrize("item", UNCLEAR, ids=lambda it: it["id"])
def test_unclear_question_is_refused_with_exit_2(item):
    code, out = cli(item["question"])
    assert code == 2
    assert out.startswith(("Question isn't clear: we read cause = ", "Question isn't clear. We couldn't find a cause"))
    assert "Please rephrase with more context, e.g. 'What effect does " in out
    assert "Nearest " in out and "Answer:" not in out
    code, out = cli("--json", item["question"])
    doc = json.loads(out)
    assert code == 2 and doc["unclear"]["message"].startswith("Question isn't clear")
    assert "status" not in doc


def test_unclear_suggestions_are_nearest_labels():
    code, out = cli("Does yodelling increase bird abundance?")
    assert code == 2
    assert "cause = 'yodelling' -> nothing" in out and "outcome = 'bird abundance' -> bird abundance" in out
    assert "e.g. 'What effect does <cause> have on bird abundance?'" in out
    suggestions = next(x for x in out.splitlines() if x.startswith("Nearest cause classes: "))
    assert 2 <= len(suggestions.split(": ", 1)[1].split("; ")) <= 3


def test_offtemplate_questions_offline_answer_or_refuse():
    """No endpoint: every item either answers (exit 0) or, if lexical linking misses a side, refuses (2)."""
    for item in ITEMS:
        code, out = cli("--json", item["question"])
        doc = json.loads(out)
        assert code in (0, 2), item
        assert ("unclear" in doc) == (code == 2)
        assert doc["footprint"]["calls"] == 0


# --- bugs are loud in ask, contained in the batch run -----------------------------------------------


def _inject(monkeypatch, stage: str) -> None:
    cls = type(registry.get(stage, overrides=ASK_STRATEGIES))
    method = next(iter(BASES[stage].__abstractmethods__))

    def boom(self, *a, **k):
        raise RuntimeError(f"injected {stage} bug")

    monkeypatch.setattr(cls, method, boom)


@pytest.mark.parametrize("stage", RUNTIME_STAGES)
def test_stage_bug_raises_in_ask(stage, monkeypatch):
    _inject(monkeypatch, stage)
    with pytest.raises(RuntimeError, match=f"injected {stage} bug"):
        cli(ANSWERED_Q)


@pytest.mark.parametrize("stage", RUNTIME_STAGES)
def test_same_bug_in_batch_run_still_writes_every_id(stage, monkeypatch, tmp_path, graph):
    _inject(monkeypatch, stage)
    qs = [{"id": it["id"], "question": it["question"]} for it in ITEMS[:5] + UNCLEAR[:2]]
    qs.append({"id": "T-1", "question": "What effect does mulch & surface cover have on bare ground?"})
    qfile, out = tmp_path / "q.yaml", tmp_path / "answers.json"
    qfile.write_text(yaml.safe_dump({"questions": qs}))
    pipeline.run_file(qfile, out, Settings(strategies=ASK_STRATEGIES))
    doc = json.loads(out.read_text())
    res = validate_answers(doc, set(graph.edges), [q.id for q in load_questions(qfile)])
    assert not res["errors"], res["errors"][:5]


def test_ask_process_exits_nonzero_with_traceback(tmp_path):
    """Through the real entry point: an injected retriever bug gives a traceback and exit code != 0."""
    (tmp_path / "sitecustomize.py").write_text(
        "from camoreasoning import registry\n"
        "def boom(self, *a, **k):\n    raise RuntimeError('injected retriever bug')\n"
        "type(registry.get('retriever')).retrieve = boom\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRINE_")}
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(ROOT / "src"), env.get("PYTHONPATH", "")])
    r = subprocess.run([sys.executable, "-m", "camoreasoning", "ask", ANSWERED_Q], env=env, cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)  # fmt: skip
    assert r.returncode != 0
    assert "Traceback" in r.stderr and "injected retriever bug" in r.stderr
    assert "Answer:" not in r.stdout


# --- dead or faulty LLM: never crash, under 10 s per question ---------------------------------------


def _timed_all(questions: list[str]) -> list[tuple[str, int, float, dict]]:
    rows = []
    for q in questions:
        t0 = time.perf_counter()
        code, out = cli("--json", q)
        dt = time.perf_counter() - t0
        assert code in (0, 2), q
        assert dt < 10, f"{q!r} took {dt:.1f} s"
        rows.append((q, code, dt, json.loads(out)))
    return rows


def test_unset_llm_all_questions_under_10s():
    _timed_all([it["question"] for it in ITEMS + UNCLEAR])


@pytest.mark.robust
@pytest.mark.parametrize("url", ["http://127.0.0.1:9/v1", "http://no-such-host.invalid/v1"])
def test_dead_llm_never_crashes(url, monkeypatch):
    monkeypatch.setenv("BRINE_URL", url)
    monkeypatch.setenv("BRINE_MODEL", "x")
    for _, _, _, doc in _timed_all([it["question"] for it in ITEMS + UNCLEAR]):
        assert doc["footprint"]["calls"] <= 2  # one request, plus llm.py's single retry on network errors


@pytest.mark.robust
@pytest.mark.xfail(strict=True, raises=ValueError, reason=MALFORMED_URL_BUG)
def test_malformed_llm_url_never_crashes(monkeypatch):
    monkeypatch.setenv("BRINE_URL", "not a url")
    monkeypatch.setenv("BRINE_MODEL", "x")
    _timed_all(["What's the relationship between peatland rewetting and methane emissions?"])


@pytest.mark.robust
@pytest.mark.parametrize("mode", ["http500", "garbage", "html", "empty_choices", "wrong_ids", "timeout"])
def test_faulty_llm_never_crashes(mode, monkeypatch):
    fake = FakeLLM(mode)
    try:
        monkeypatch.setenv("BRINE_URL", fake.url)
        monkeypatch.setenv("BRINE_MODEL", "fake")
        for _, _, _, doc in _timed_all([it["question"] for it in ITEMS + UNCLEAR]):
            assert doc["footprint"]["calls"] <= 2
    finally:
        fake.close()


def _pick_first_option(mode: str, body: dict) -> tuple[int, str]:
    """A cooperative model: for every side sent, pick the first candidate id."""
    user = body["messages"][-1]["content"].replace(" /no_think", "")
    reply = {}
    for line in user.splitlines():
        if line.startswith("{"):
            it = json.loads(line)
            reply[it["id"]] = {k: it[k]["options"][0]["id"] for k in ("cause", "outcome") if k in it}
    return 200, json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}],
                            "usage": {"prompt_tokens": 100, "completion_tokens": 10}})  # fmt: skip


@pytest.mark.robust
def test_assisted_linker_uses_at_most_one_call_per_question(monkeypatch):
    monkeypatch.setattr(fake_llm, "reply_for", _pick_first_option)
    fake = FakeLLM("ok")
    try:
        monkeypatch.setenv("BRINE_URL", fake.url)
        monkeypatch.setenv("BRINE_MODEL", "fake")
        rows = _timed_all([it["question"] for it in ITEMS])
        assert all(doc["footprint"]["calls"] <= 1 for *_, doc in rows)
        assert len(fake.requests) <= len(ITEMS)
        # OT-08's cause ("peatland rewetting") has no lexical class; the LLM fallback links it.
        ot08 = next(doc for q, _, _, doc in rows if q == ITEMS[7]["question"])
        assert "unclear" not in ot08 and ot08["footprint"]["calls"] == 1
    finally:
        fake.close()


@pytest.mark.robust
def test_hung_llm_still_answers_within_10s(monkeypatch):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    held: list[socket.socket] = []
    threading.Thread(target=lambda: [held.append(srv.accept()[0]) for _ in range(8)], daemon=True).start()
    try:
        monkeypatch.setenv("BRINE_URL", f"http://127.0.0.1:{srv.getsockname()[1]}/v1")
        monkeypatch.setenv("BRINE_MODEL", "x")
        _timed_all([ITEMS[7]["question"]])
    finally:
        for s in held:
            s.close()
        srv.close()
