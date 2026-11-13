"""Orchestration. Frozen guarantees: batch-first linking (one LLM round for all questions), per-question
fault isolation, and answers.json always written with one entry per question id."""

from __future__ import annotations

import json
import traceback
from collections.abc import Sequence
from pathlib import Path

from camoreasoning import registry
from camoreasoning.answers import load_questions, write_answers
from camoreasoning.components import Context
from camoreasoning.config import OUTPUTS_DIR, RUNTIME_STAGES, Settings, load_settings
from camoreasoning.contracts import Answer, Features, Frame, ParsedQuestion, Question, Side, Trace
from camoreasoning.graph import Graph, load_graph
from camoreasoning.llm import LLM
from camoreasoning.meter import Meter
from camoreasoning.taxonomy import Taxonomy, load_taxonomy


def make_context(
    settings: Settings | None = None,
    *,
    out_dir: Path = OUTPUTS_DIR,
    graph: Graph | None = None,
    taxonomy: Taxonomy | None = None,
    meter: Meter | None = None,
) -> Context:
    settings = settings or load_settings()
    meter = meter or Meter(max_calls=settings.max_calls)
    return Context(
        graph=graph or load_graph(),
        taxonomy=taxonomy if taxonomy is not None else load_taxonomy(),
        llm=LLM(settings, meter),
        settings=settings,
        out_dir=Path(out_dir),
    )


def fallback_answer(q: Question, reason: str) -> Answer:
    """Last-resort entry: parseable, honest, mid confidence (never full-confidence wrong)."""
    return Answer(
        id=q.id,
        status="no_evidence",
        answer="This question could not be evaluated against the graph.",
        confidence=0.5,
        searched_for=f"evaluation failed before search completed ({reason[:160]})",
    )


def features_of(frame: Frame, candidates, verdict, certainty) -> Features:
    inc = verdict.included
    nulls = sum(1 for v in inc if v.effect == 0)
    return Features(
        status=verdict.status,
        direction=verdict.direction,
        certainty=certainty,
        n_docs=len({v.doc_id for v in inc}),
        n_edges=len(inc),
        agreement=verdict.agreement,
        null_share=nulls / len(inc) if inc else 0.0,
        n_reversed=len(candidates.reversed),
        link_via=frame.via,
        link_margin=frame.margin,
        template_hit=frame.parsed.template_hit,
    )


class Pipeline:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.s = {st: registry.get(st, overrides=ctx.settings.strategies) for st in RUNTIME_STAGES}

    def parse(self, q: Question) -> ParsedQuestion:
        try:
            return self.s["parser"].parse(q, self.ctx)
        except Exception:
            return ParsedQuestion(question=q, cause_text=None, outcome_text=None, template_hit=False)

    def link(self, parsed: Sequence[ParsedQuestion]) -> list[Frame]:
        """Configured linker, else baseline linker, else empty frames. Always len(parsed) frames."""
        linkers = [self.s["linker"]]
        if self.s["linker"].name != "baseline":
            linkers.append(registry.get("linker", "baseline"))
        for linker in linkers:
            try:
                frames = linker.link(parsed, self.ctx)
                if len(frames) == len(parsed):
                    return frames
            except Exception:
                traceback.print_exc()
        return [Frame(p, Side(p.cause_text), Side(p.outcome_text), "none", 0.0) for p in parsed]

    def answer_one(self, frame: Frame) -> tuple[Answer, Trace]:
        ctx, s = self.ctx, self.s
        q = frame.parsed.question
        cands = s["retriever"].retrieve(frame, ctx)
        votes = s["interpreter"].interpret(cands, ctx)
        verdict = s["aggregator"].aggregate(votes, cands, ctx)
        certainty = s["grader"].grade(verdict, ctx)
        feats = features_of(frame, cands, verdict, certainty)
        conf = min(1.0, max(0.0, float(s["calibrator"].confidence(feats, ctx))))
        edge_ids = s["citer"].cite(verdict, ctx) if verdict.status == "answered" else []
        text, searched = s["renderer"].render(verdict, cands, certainty, ctx)
        answer = Answer(
            id=q.id,
            status=verdict.status,
            answer=text,
            confidence=conf,
            direction=verdict.direction,
            certainty=certainty if verdict.status == "answered" else None,
            edge_ids=edge_ids,
            searched_for=searched if verdict.status == "no_evidence" else None,
        )
        return answer, Trace(q, frame, cands, verdict, feats)

    def run(self, questions: Sequence[Question]) -> tuple[list[Answer], list[Trace]]:
        self.ctx.llm.meter.questions += len(questions)
        frames = self.link([self.parse(q) for q in questions])
        answers, traces = [], []
        for q, frame in zip(questions, frames):
            try:
                a, t = self.answer_one(frame)
            except Exception as e:
                traceback.print_exc()
                a, t = fallback_answer(q, f"{type(e).__name__}: {e}"), Trace(q, frame, error=repr(e))
            try:
                a.extras = self.s["extras"].write_question(a, t, self.ctx)
            except Exception:
                a.extras = []
            answers.append(a)
            traces.append(t)
        try:
            self.s["extras"].write_run(answers, traces, self.ctx)
        except Exception:
            traceback.print_exc()
        return answers, traces


def run_file(questions_path: Path, answers_path: Path, settings: Settings | None = None) -> dict:
    """The judged entry point. Writes answers.json no matter what, plus footprint.json beside extras."""
    settings = settings or load_settings()
    answers_path = Path(answers_path).resolve()
    out_dir = answers_path.parent if answers_path.parent.name == "outputs" else answers_path.parent / "outputs"
    questions: list[Question] = []
    answers: list[Answer] = []
    ctx = None
    try:
        questions = load_questions(questions_path)
        ctx = make_context(settings, out_dir=out_dir)
        answers, _ = Pipeline(ctx).run(questions)
    except Exception as e:
        traceback.print_exc()
        reason = f"{type(e).__name__}: {e}"
        done = {a.id for a in answers}
        answers += [fallback_answer(q, reason) for q in questions if q.id not in done]
    finally:
        write_answers(answers_path, settings.team, answers)
    summary = ctx.llm.meter.summary() if ctx else {}
    if ctx:
        ctx.llm.meter.write(out_dir / "footprint.json")
    return {"answers": len(answers), "path": str(answers_path), **summary}


def ask(text: str, settings: Settings | None = None, out_dir: Path = OUTPUTS_DIR) -> dict:
    """One free-form question (judges' live question). Returns the answers.json entry."""
    ctx = make_context(settings, out_dir=out_dir)
    answers, _ = Pipeline(ctx).run([Question(id="ASK", text=" ".join(text.split()))])
    return {**answers[0].to_json(), "footprint": {k: v for k, v in ctx.llm.meter.summary().items() if k != "log"}}


def dumps(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)
