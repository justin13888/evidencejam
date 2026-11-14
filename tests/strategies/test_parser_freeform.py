"""freeform parser: off-template shapes from experiments/ask/offtemplate.yaml, exact baseline parity on
template questions (dev set + practice set), and never raising on hostile strings."""

from __future__ import annotations

import random
import string
import time

import pytest
import yaml

from camoreasoning import registry
from camoreasoning.answers import load_questions
from camoreasoning.config import DEVSETS_DIR, EXPERIMENTS_DIR, ROOT
from camoreasoning.contracts import ParsedQuestion, Question
from tests.conftest import FUZZ

OFFTEMPLATE = yaml.safe_load((EXPERIMENTS_DIR / "ask" / "offtemplate.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def parsers():
    return registry.get("parser", "baseline"), registry.get("parser", "freeform")


@pytest.fixture
def ctx(make_ctx):
    return make_ctx()


def test_offtemplate_file_shape():
    assert len(OFFTEMPLATE["items"]) == 20 and len({it["id"] for it in OFFTEMPLATE["items"]}) == 20
    assert len(OFFTEMPLATE["unclear"]) >= 3


@pytest.mark.parametrize("item", OFFTEMPLATE["items"], ids=lambda it: it["id"])
def test_offtemplate_spans(item, parsers, ctx):
    p = parsers[1].parse(Question(item["id"], item["question"]), ctx)
    assert (p.cause_text or "").lower() == item["cause"].lower()
    assert (p.outcome_text or "").lower() == item["outcome"].lower()
    assert p.template_hit is False


@pytest.mark.parametrize("item", OFFTEMPLATE["unclear"][:4], ids=lambda it: it["id"])
def test_vague_questions_yield_no_spans(item, parsers, ctx):
    p = parsers[1].parse(Question(item["id"], item["question"]), ctx)
    assert p.cause_text is None or p.outcome_text is None


def _dev_and_practice() -> list[Question]:
    rows = yaml.safe_load((DEVSETS_DIR / "generated.yaml").read_text(encoding="utf-8"))["items"]
    return [Question(r["id"], r["question"]) for r in rows] + load_questions(ROOT / "questions.yaml")


def test_template_questions_parse_exactly_like_baseline(parsers, ctx):
    base, free = parsers
    qs = _dev_and_practice()
    hits = 0
    for q in qs:
        b = base.parse(q, ctx)
        if b.template_hit:
            hits += 1
            assert free.parse(q, ctx) == b, q
    assert hits >= 178, "every generated dev question is in the hidden-set template"


def test_template_hit_only_when_baseline_hits(parsers, ctx):
    base, free = parsers
    for q in _dev_and_practice() + [Question(it["id"], it["question"]) for it in OFFTEMPLATE["items"]]:
        assert free.parse(q, ctx).template_hit == base.parse(q, ctx).template_hit


@pytest.mark.parametrize(
    "text, cause, outcome",
    [
        ("In restored wetlands, does sediment removal increase fish abundance?", "sediment removal", "fish abundance"),
        ("Does burning increase native richness, in restored prairies?", "burning", "native richness"),
        ("What is the effect of mowing on invasive cover in Ontario grasslands?", "mowing", "invasive cover"),
        ("Is plant cover changed by trampling compared to control plots?", "trampling", "plant cover"),
        ("what  effect  does Mulch have on  WEEDS", "Mulch", "WEEDS"),
        ("Relationship between grazing and bird abundance", "grazing", "bird abundance"),
        ("Does nitrogen in soil increase tree growth?", "nitrogen in soil", "tree growth"),  # not a context noun
    ],
)
def test_context_and_shapes(text, cause, outcome, parsers, ctx):
    p = parsers[1].parse(Question("x", text), ctx)
    assert (p.cause_text, p.outcome_text) == (cause, outcome)


def _random_strings(n: int, seed: int = 7) -> list[str]:
    rng = random.Random(seed)
    alphabet = string.printable + "“”‘’—–…éßπ🦝​­﻿()[],;:?!"
    words = ["what", "effect", "does", "have", "on", "is", "by", "and", "of", "the", "in", "affected", "(", ","]
    out = []
    for i in range(n):
        if i % 2:
            out.append("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 200))))
        else:
            out.append(" ".join(rng.choice(words) for _ in range(rng.randint(0, 40))))
    return out


HOSTILE = [
    *FUZZ,
    None,
    "\x00\x01\x02",
    "(" * 3000,
    "does " * 2000 + "affect",
    "what effect of " * 500 + " on " * 500,
    "is " + "a " * 3000 + "affected by " + "b " * 3000,
    "In " + "x" * 79 + ", " * 50,
    "🦝 does 🦝 affect 🦝?",
    "Ｗｈａｔ ｅｆｆｅｃｔ ｄｏｅｓ ｆｉｒｅ ｈａｖｅ ｏｎ ｂｉｒｄｓ？",
]


def test_never_raises_on_hostile_or_random_strings(parsers, ctx):
    free = parsers[1]
    t0 = time.perf_counter()
    for s in HOSTILE + _random_strings(400):
        q = Question("f", s)  # type: ignore[arg-type]
        p = free.parse(q, ctx)
        assert isinstance(p, ParsedQuestion) and p.question is q
        for span in (p.cause_text, p.outcome_text):
            assert span is None or (isinstance(span, str) and span.strip())
    assert time.perf_counter() - t0 < 10, "regexes must stay linear on long inputs"
    assert ctx.llm.meter.calls == 0
