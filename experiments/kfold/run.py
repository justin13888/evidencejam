"""Read-only k-fold over pooled dev for #120 (calibrators) and #82 (unseen-question accuracy). 0 LLM calls.

    PYTHONPATH=src .venv/bin/python experiments/kfold/run.py   # -> experiments/results/kfold_dev.json

One pipeline run over pooled dev (class_gold + gold_annotated, defaults). Never reads holdout (#12, #48).

#120: repeated stratified 5-fold (stratified by file x predicted status, 50 seeds). Each calibrator is fit on
the train folds and predicts the held-out fold; out-of-fold predictions are pooled into one 267-row
prediction per seed and scored with `evaluate.calibration` (the same 10-bin ECE and Brier as `mise run eval`),
pooled and per file. Mean and 5-95% spread over seeds. Per-fold ECE (n ~ 53) is also reported but is biased
up by small bins.
  baseline   constant 0.6 (shipped)
  constant   train-fold accuracy
  two_cell   train-fold accuracy per predicted status, capped at 0.95
  binned     calibrator/binned refitted per fold (fit_params)

#82: the pipeline is not fitted, so k-fold over dev only re-reads the dev accuracy: it cannot undo fixes a
person tuned on dev items. Reported instead: the dev accuracy with a bootstrap 95% CI, and accuracy by when
an item entered the devset (items labelled after most dev-driven fixes landed are closer to unseen).
"""

from __future__ import annotations

import json
import random
import statistics as st
import subprocess
from collections import defaultdict
from pathlib import Path

import yaml

from camoreasoning.config import CACHE_DIR, DEVSETS_DIR, RESULTS_DIR, load_settings
from camoreasoning.contracts import Question
from camoreasoning.evaluate import calibration, is_correct, load_devsets
from camoreasoning.pipeline import Pipeline, make_context
from camoreasoning.strategies.calibrator import binned

FILES = ("class_gold.yaml", "gold_annotated.yaml")
K, SEEDS, BOOT = 5, 50, 2000
CAP = 0.95


def fit(name: str, train: list[tuple]) -> callable:
    ys = [y for _, y, _ in train]
    if name == "baseline":
        return lambda f: 0.6
    if name == "constant":
        p = sum(ys) / len(ys)
        return lambda f: p
    if name == "two_cell":
        g = sum(ys) / len(ys)
        by = defaultdict(list)
        for f, y, _ in train:
            by[f.status].append(y)
        p = {s: min(CAP, sum(v) / len(v)) for s, v in by.items()}
        return lambda f: p.get(f.status, g)
    if name == "binned":
        params = binned.fit_params([(f, y) for f, y, _ in train])
        return lambda f: binned.predict(params, f)
    raise ValueError(name)


CALIBRATORS = ("baseline", "constant", "two_cell", "binned")


def folds(rows: list[tuple], seed: int) -> list[list[int]]:
    strata = defaultdict(list)
    for i, (f, _, file) in enumerate(rows):
        strata[(file, f.status)].append(i)
    rng = random.Random(seed)
    out: list[list[int]] = [[] for _ in range(K)]
    j = 0
    for key in sorted(strata):
        idx = strata[key][:]
        rng.shuffle(idx)
        for i in idx:
            out[j % K].append(i)
            j += 1
    return out


def summary(xs: list[float]) -> dict:
    xs = sorted(xs)
    q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]  # noqa: E731
    return {"mean": round(st.mean(xs), 4), "p05": round(q(0.05), 4), "p95": round(q(0.95), 4)}


def added_in(path: Path) -> dict[str, str]:
    """Item id -> first commit time (YYYY-MM-DDTHH:MM, committer zone) whose version of the file labels it."""
    log = subprocess.run(["git", "log", "--reverse", "--format=%H %cd", "--date=format:%Y-%m-%dT%H:%M", "--",
                          str(path)], capture_output=True, text=True, check=True).stdout.split("\n")  # fmt: skip
    seen: dict[str, str] = {}
    for line in filter(None, log):
        sha, when = line.split(" ", 1)
        blob = subprocess.run(["git", "show", f"{sha}:{path.relative_to(Path.cwd())}"], capture_output=True,
                              text=True).stdout  # fmt: skip
        try:
            items = (yaml.safe_load(blob) or {}).get("items") or []
        except yaml.YAMLError:
            continue
        for it in items:
            if it.get("status") is not None and it.get("split", "dev") == "dev":
                seen.setdefault(it["id"], when)
    return seen


def main() -> None:
    settings = load_settings()
    paths = [DEVSETS_DIR / f for f in FILES]
    gold = load_devsets(paths, "dev")
    origin = {g.id: p.name for p in paths for g in load_devsets([p], "dev")}
    ctx = make_context(settings, out_dir=CACHE_DIR / "eval" / "kfold")
    answers, traces = Pipeline(ctx).run([Question(g.id, g.question) for g in gold])
    calls = ctx.llm.meter.summary().get("calls_per_question")
    by_id = {a.id: a for a in answers}
    rows = [(t.features, is_correct(g, by_id[g.id]), origin[g.id]) for g, t in zip(gold, traces)]
    ids = [g.id for g in gold]

    # --- #120 ---
    pooled = {c: defaultdict(list) for c in CALIBRATORS}
    per_fold = {c: defaultdict(list) for c in CALIBRATORS}
    for seed in range(SEEDS):
        oof = {c: [0.0] * len(rows) for c in CALIBRATORS}
        for held in folds(rows, seed):
            hs = set(held)
            train = [r for i, r in enumerate(rows) if i not in hs]
            for c in CALIBRATORS:
                pred = fit(c, train)
                for i in held:
                    oof[c][i] = pred(rows[i][0])
                cal = calibration([oof[c][i] for i in held], [rows[i][1] for i in held])
                per_fold[c]["ece"].append(cal["ece"])
                per_fold[c]["brier"].append(cal["brier"])
        for c in CALIBRATORS:
            for scope in ("pooled", *FILES):
                sel = [i for i, r in enumerate(rows) if scope == "pooled" or r[2] == scope]
                cal = calibration([oof[c][i] for i in sel], [rows[i][1] for i in sel])
                pooled[c][f"{scope}.ece"].append(cal["ece"])
                pooled[c][f"{scope}.brier"].append(cal["brier"])
    cv = {c: {k: summary(v) for k, v in pooled[c].items()} for c in CALIBRATORS}
    cv_fold = {c: {k: summary(v) for k, v in per_fold[c].items()} for c in CALIBRATORS}
    # paired: share of seeds where two_cell beats baseline on pooled oof ECE / Brier
    paired = {
        m: round(sum(a < b for a, b in zip(pooled["two_cell"][f"pooled.{m}"], pooled["baseline"][f"pooled.{m}"]))
                 / SEEDS, 3)
        for m in ("ece", "brier")
    }  # fmt: skip
    in_sample = {}
    for c in CALIBRATORS:
        pred = fit(c, rows)
        in_sample[c] = calibration([pred(f) for f, _, _ in rows], [y for _, y, _ in rows])
        in_sample[c].pop("bins")

    # --- #82 ---
    ys = [y for _, y, _ in rows]
    rng = random.Random(0)
    boot = sorted(st.mean(rng.choices(ys, k=len(ys))) for _ in range(BOOT))
    when = {}
    for p in paths:
        when |= added_in(p)
    by_day = defaultdict(list)
    status = {g.id: g.status for g in gold}
    for i, (_, y, file) in zip(ids, rows):
        by_day[(file, when.get(i, "?")[:16], status[i])].append(y)
    accuracy = {
        "pooled": round(st.mean(ys), 4),
        "bootstrap_95": [round(boot[int(0.025 * BOOT)], 4), round(boot[int(0.975 * BOOT)], 4)],
        "by_file": {f: round(st.mean([y for _, y, fl in rows if fl == f]), 4) for f in FILES},
        "by_added_and_gold_status": {
            f"{f} @ {d} / {s}": {"n": len(v), "accuracy": round(st.mean(v), 4)}
            for (f, d, s), v in sorted(by_day.items())
        },  # fmt: skip
    }
    out = {
        "n": len(rows), "k": K, "seeds": SEEDS, "calls_per_question": calls,
        "issue_120": {"cv_oof": cv, "cv_per_fold": cv_fold, "two_cell_beats_baseline_share": paired,
                      "in_sample": in_sample},
        "issue_82": accuracy,
    }  # fmt: skip
    dst = RESULTS_DIR / "kfold_dev.json"
    dst.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({c: {k: v["mean"] for k, v in cv[c].items()} for c in CALIBRATORS}, indent=1))
    print(json.dumps({"paired": paired, "in_sample": in_sample}, indent=1))
    print(json.dumps(accuracy, indent=1))


if __name__ == "__main__":
    main()
