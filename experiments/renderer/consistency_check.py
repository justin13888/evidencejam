"""Item 15 done-check (issue #15): D1, vote-count and direction consistency over every answered result.

Populations, all under the current default strategies (camoreasoning.strategies.DEFAULTS):
- pairs: every cause x outcome class pair of the real taxonomy (linker bypassed: frames name the
  classes, labels as the question spans), the same population review_sample.py draws from;
- questions: questions.yaml, through the full pipeline;
- dev: the dev split of experiments/devsets, through the full pipeline (never the holdout).

Each answered text is checked by `strategies.renderer.consistency.violations`. Prints a JSON summary and
every violation; exits 1 if there is any. 0 LLM calls (the pipeline's parser/linker defaults are offline).

    python experiments/renderer/consistency_check.py [--only pairs|questions|dev]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from camoreasoning import registry
from camoreasoning.config import CACHE_DIR, ROOT, Settings
from camoreasoning.contracts import Frame, ParsedQuestion, Question, Ref, Side
from camoreasoning.evaluate import load_devsets
from camoreasoning.pipeline import Pipeline, make_context
from camoreasoning.strategies import DEFAULTS
from camoreasoning.strategies.grader.rubric import is_associational
from camoreasoning.strategies.renderer.consistency import violations

STAGES = ("retriever", "interpreter", "aggregator", "grader", "renderer", "citer")


def uncited_studies(v, cited: list[str]) -> list[str]:
    """Studies the text counts (one per `doc_effects` entry) with no edge among the citations (#100)."""
    docs = {x.doc_id for x in v.included if x.edge_id in set(cited)}
    return sorted(d for d, _ in v.doc_effects if d not in docs)


def check_pairs(ctx) -> tuple[int, list[dict]]:
    """Every class pair through retriever -> renderer with the default strategies."""
    s = {st: registry.get(st, DEFAULTS[st]) for st in STAGES}
    tax = ctx.taxonomy
    causes = [c for c in tax.classes.values() if c.kind in ("cause", "both")]
    outcomes = [c for c in tax.classes.values() if c.kind in ("outcome", "both")]
    n, bad = 0, []
    for c in causes:
        for o in outcomes:
            if c.id == o.id:
                continue
            cause, outcome = c.label.lower(), o.label.lower()
            q = Question(f"{c.id}->{o.id}", f"What effect does {cause} have on {outcome}?")
            frame = Frame(ParsedQuestion(q, cause, outcome, True), Side(cause, (Ref(c.id),)),
                          Side(outcome, (Ref(o.id),)), "regex", 1.0)  # fmt: skip
            cands = s["retriever"].retrieve(frame, ctx)
            if not cands.forward:
                continue
            v = s["aggregator"].aggregate(s["interpreter"].interpret(cands, ctx), cands, ctx)
            if v.status != "answered":
                continue
            text, _ = s["renderer"].render(v, cands, s["grader"].grade(v, ctx), ctx)
            assoc = bool(v.included) and all(is_associational(x, ctx) for x in v.included)
            n += 1
            errs = violations(text, v, assoc, (cause, outcome))
            if miss := uncited_studies(v, s["citer"].cite(v, ctx)):
                errs = [*errs, f"studies counted but not cited: {miss}"]
            if errs:
                bad.append({"id": q.id, "text": text, "violations": errs})
    return n, bad


def check_questions(ctx, questions: list[Question]) -> tuple[int, list[dict]]:
    """Questions through the full pipeline; the trace carries the verdict the text rendered."""
    answers, traces = Pipeline(ctx).run(questions)
    tr = {t.question.id: t for t in traces}
    n, bad = 0, []
    for a in answers:
        t = tr.get(a.id)
        if a.status != "answered" or not t or not t.verdict or not t.candidates:
            continue
        v, f = t.verdict, t.candidates.frame
        assoc = bool(v.included) and all(is_associational(x, ctx) for x in v.included)
        n += 1
        errs = violations(a.answer, v, assoc, (f.cause.text or "", f.outcome.text or ""))
        if miss := uncited_studies(v, a.edge_ids):
            errs = [*errs, f"studies counted but not cited: {miss}"]
        if errs:
            bad.append({"id": a.id, "text": a.answer, "violations": errs})
    return n, bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=("pairs", "questions", "dev"))
    args = ap.parse_args()
    ctx = make_context(Settings(), out_dir=CACHE_DIR / "consistency_check")
    raw = yaml.safe_load(Path(ROOT / "questions.yaml").read_text(encoding="utf-8")) or []
    raw = raw.get("questions", raw) if isinstance(raw, dict) else raw
    runs = {
        "pairs": lambda: check_pairs(ctx),
        "questions": lambda: check_questions(ctx, [Question(str(q["id"]), q["question"]) for q in raw]),
        "dev": lambda: check_questions(ctx, [Question(g.id, g.question) for g in load_devsets(None, "dev")]),
    }
    summary, failures = {}, []
    for name, run in runs.items():
        if args.only and name != args.only:
            continue
        n, bad = run()
        summary[name] = {"answered": n, "violations": len(bad)}
        failures += [{"population": name, **b} for b in bad]
    print(json.dumps({"summary": summary, "failures": failures}, indent=2, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
