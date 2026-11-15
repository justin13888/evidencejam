"""One pass of the pipeline over the pooled holdout -> experiments/calibration/holdout_report.json.

Issue #12 gates the calibrator on holdout ECE <= 0.05, checked on all holdout items pooled (node + class files,
issue #48), with each file reported alongside. Run it once, after the fit, and never tune on what it prints:

    CAMOREASONING_STRATEGY_CALIBRATOR=binned mise run calibrate      # fit on dev only
    CAMOREASONING_STRATEGY_CALIBRATOR=binned python experiments/calibration/holdout_report.py

It scores the same answers `mise run eval:holdout` scores (one pipeline run, no second pass per file), and also
keeps one row per item (gold, prediction, confidence, correct) so pages built later (the honest-limits page,
issue #20) read their failures from this file instead of running the holdout again. The baseline line is the
constant 0.6 confidence applied to the same answers, for reference.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from camoreasoning import registry
from camoreasoning.config import CACHE_DIR, CALIBRATION_DIR, DEVSETS_DIR, load_settings
from camoreasoning.contracts import Question
from camoreasoning.evaluate import calibration, is_correct, load_devsets, score
from camoreasoning.strategies.calibrator.baseline import CONSTANT

TARGET_ECE = 0.05
HEADLINE = ("n", "accuracy", "no_evidence_precision", "no_evidence_recall", "calibration", "by_tag")


def headline(res: dict) -> dict:
    return {k: res.get(k) for k in HEADLINE}


def main(argv: list[str]) -> int:
    from camoreasoning.pipeline import Pipeline, make_context

    dst = Path(argv[0]) if argv else CALIBRATION_DIR / "holdout_report.json"
    settings = load_settings()
    gold = sorted(load_devsets(split="holdout"), key=lambda g: g.id)
    files = {p.name: {g.id for g in load_devsets([p], "holdout")} for p in sorted(DEVSETS_DIR.glob("*.yaml"))}
    files = {name: ids for name, ids in files.items() if ids}
    origin = {i: name for name, ids in files.items() for i in ids}

    ctx = make_context(settings, out_dir=CACHE_DIR / "eval" / "holdout_report")
    answers, _ = Pipeline(ctx).run([Question(g.id, g.question) for g in gold])
    footprint = ctx.llm.meter.summary()
    by_id = {a.id: a for a in answers}

    pooled = score(gold, answers, footprint)
    per_file = {name: headline(score([g for g in gold if g.id in ids], answers)) for name, ids in files.items()}
    correct = [g.id in by_id and is_correct(g, by_id[g.id]) for g in gold]
    baseline = [CONSTANT[by_id[g.id].status] if g.id in by_id else 1.0 for g in gold]
    ece = pooled["calibration"]["ece"]
    items = []
    for g, ok in zip(gold, correct):
        a = by_id.get(g.id)
        items.append({
            "id": g.id, "file": origin.get(g.id), "tags": list(g.tags), "question": g.question,
            "gold": {"status": g.status, "direction": g.direction, "certainty": g.certainty},
            "predicted": {"status": a.status, "direction": a.direction, "certainty": a.certainty} if a else None,
            "confidence": a.confidence if a else None, "correct": ok,
        })  # fmt: skip
    report = {
        "split": "holdout",
        "calibrator": registry.get("calibrator", overrides=settings.strategies).name,
        "target_ece": TARGET_ECE,
        "passes": ece is not None and ece <= TARGET_ECE,
        "pooled": headline(pooled),
        "files": per_file,
        "baseline_constant": calibration(baseline, correct),
        "calls_per_question": footprint.get("calls_per_question"),
        "items": items,
    }
    dst.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = {"pooled_n": pooled["n"], "pooled_ece": ece, "passes": report["passes"]}
    summary |= {name: {"n": r["n"], "ece": r["calibration"]["ece"]} for name, r in per_file.items()}
    print(json.dumps(summary | {"path": str(dst)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
