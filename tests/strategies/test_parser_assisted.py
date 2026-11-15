"""parser/assisted (issue #114): freeform first, a 0-call how-to rule, then one ctx.llm call. ctx.llm is mocked."""

from __future__ import annotations

import contextlib
import dataclasses
import io

import pytest

from camoreasoning import pipeline, registry
from camoreasoning.cli import main
from camoreasoning.contracts import Question
from camoreasoning.llm import LLMError
from camoreasoning.strategies.parser.assisted import causes_with_evidence, control_target
from camoreasoning.taxonomy import load_taxonomy

GARLIC = "How do I control garlic mustard?"
DOGWOOD = "We burned last spring and the dogwood is already back. Should we burn again this year?"


class StubLLM:
    """Stands in for ctx.llm: records calls; replies with `reply` or raises it if it is an exception."""

    def __init__(self, reply, available: bool = True):
        self.reply, self.available, self.calls = reply, available, []

    def chat_json(self, system, user, *, max_tokens=256, purpose=""):
        self.calls.append(user)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def parse(make_ctx):
    parser = registry.get("parser", "assisted")

    def run(text: str, llm: StubLLM):
        ctx = dataclasses.replace(make_ctx(), llm=llm)
        return parser.parse(Question("Q", text), ctx)

    return run


def test_template_question_makes_no_call(parse):
    llm = StubLLM({"cause": "x", "outcome": "y"})
    p = parse("What effect does prescribed burning have on native plant richness?", llm)
    assert p.template_hit and (p.cause_text, p.outcome_text) == ("prescribed burning", "native plant richness")
    assert llm.calls == []


def test_freeform_shape_makes_no_call(parse):
    llm = StubLLM({"cause": "x", "outcome": "y"})
    p = parse("Does mulching lead to more invasive plants?", llm)
    assert (p.cause_text, p.outcome_text) == ("mulching", "invasive plants") and llm.calls == []


@pytest.mark.parametrize(
    ("text", "target"),
    [
        (GARLIC, "garlic mustard abundance"),
        ("How can we get rid of buckthorn in our woodlot?", "buckthorn abundance"),
        ("What's the best way to reduce reed canary grass cover?", "reed canary grass cover"),
        ("Does mulch work?", None),
    ],
)
def test_control_target(text, target):
    assert control_target(text) == target


def test_garlic_mustard_is_an_open_cause_question_without_a_call(parse):
    llm = StubLLM({"cause": "x", "outcome": "y"})
    p = parse(GARLIC, llm)
    assert (p.cause_text, p.outcome_text) == (None, "garlic mustard abundance") and llm.calls == []


def test_dogwood_story_parses_with_one_call(parse):
    llm = StubLLM({"cause": "prescribed burning", "outcome": "dogwood abundance"})
    p = parse(DOGWOOD, llm)
    assert (p.cause_text, p.outcome_text) == ("prescribed burning", "dogwood abundance")
    assert not p.template_hit and len(llm.calls) == 1 and "dogwood" in llm.calls[0]


@pytest.mark.parametrize(
    "reply",
    [LLMError("timeout"), "not a dict", ["x"], {"cause": None, "outcome": None}, {"cause": 3, "outcome": "x" * 500}],
)
def test_llm_failure_or_junk_keeps_freeform(parse, reply):
    llm = StubLLM(reply)
    p = parse(DOGWOOD, llm)
    base = registry.get("parser", "freeform").parse(Question("Q", DOGWOOD), None)
    assert (p.cause_text, p.outcome_text) == (base.cause_text, base.outcome_text) and len(llm.calls) == 1


def test_no_endpoint_makes_no_call(parse):
    llm = StubLLM({"cause": "a", "outcome": "b"}, available=False)
    parse(DOGWOOD, llm)
    assert llm.calls == []


def test_causes_with_evidence_lists_classes_on_the_outcome(make_ctx):
    ctx = make_ctx(tax=load_taxonomy())
    parsed = registry.get("parser", "assisted").parse(Question("Q", GARLIC), ctx)
    frame = registry.get("linker", "cessation").link([parsed], ctx)[0]
    assert frame.cause.empty and not frame.outcome.empty
    causes = causes_with_evidence(frame, ctx)
    assert causes and all(n >= 1 for _, n in causes)
    assert [n for _, n in causes] == sorted((n for _, n in causes), reverse=True)


def _ask(monkeypatch, tmp_path, text: str, llm_reply=None) -> tuple[int, str]:
    for k in ("BRINE_URL", "BRINE_MODEL", "BRINE_API_KEY", "CAMOREASONING_TAXONOMY_DIR", "CAMOREASONING_LLM_CACHE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CAMOREASONING_STRATEGY_PARSER", "assisted")
    monkeypatch.setenv("CAMOREASONING_STRATEGY_LINKER", "assisted")
    monkeypatch.setattr(pipeline.ask_frame, "__defaults__", (None, tmp_path / "outputs"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["ask", text])
    return code, out.getvalue()


def test_ask_open_cause_lists_interventions_with_evidence(monkeypatch, tmp_path):
    code, out = _ask(monkeypatch, tmp_path, GARLIC)
    assert code == 2
    assert out.startswith("Your question names an outcome (garlic mustard abundance -> ")
    assert "Interventions with evidence on it: " in out and "studies)" in out
    assert "Ask e.g. 'What effect does " in out


def test_ask_refusal_wording_when_nothing_is_found(monkeypatch, tmp_path):
    code, out = _ask(monkeypatch, tmp_path, "Does it work?")
    assert code == 2
    assert out.startswith("Question isn't clear. We couldn't find a cause and an outcome in your question.")
    assert "(nothing) -> nothing" not in out
