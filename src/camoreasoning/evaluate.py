"""Local scorer mirroring the README rubric, run on labelled devsets (experiments/devsets/*.yaml).

Devset file format: {items: [{id, question, status, direction, certainty, edge_ids, tags, split, source}]}
(GoldItem fields; status null = unlabelled, skipped; duplicate ids: human labels win).
"Correct" = same status and, if answered, same direction; calibration is measured against it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

import yaml

from camoreasoning.answers import validate_entry
from camoreasoning.config import CACHE_DIR, DEVSETS_DIR, RESULTS_DIR, Settings
from camoreasoning.contracts import Answer, DevQuestion, GoldItem, Question
from camoreasoning.graph import load_graph

FIELDS = set(GoldItem.__dataclass_fields__)


def load_devsets(paths: Sequence[Path] | None = None, split: str | None = None) -> list[GoldItem]:
    out: dict[str, GoldItem] = {}
    for p in paths or sorted(DEVSETS_DIR.glob("*.yaml")):
        raw = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
        for it in raw.get("items") or []:
            if not it.get("status"):
                continue
            it = {k: v for k, v in it.items() if k in FIELDS}
            it["id"] = str(it["id"])
            g = GoldItem(**{**it, "edge_ids": tuple(it.get("edge_ids") or ()), "tags": tuple(it.get("tags") or ())})
            if (split is None or g.split == split) and (g.id not in out or g.source.startswith("human")):
                out[g.id] = g
    return list(out.values())


def save_devset(path: Path, items: Sequence[GoldItem | DevQuestion]) -> None:
    rows = []
    for it in items:
        d = asdict(it)
        d = {k: list(v) if isinstance(v, tuple) else v for k, v in d.items()}
        rows.append(d if isinstance(it, GoldItem) else {**d, "status": None})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(yaml.safe_dump({"items": rows}, sort_keys=False, allow_unicode=True), encoding="utf-8")


def is_correct(g: GoldItem, a: Answer) -> bool:
    return a.status == g.status and (g.status == "no_evidence" or a.direction == g.direction)


def calibration(conf: list[float], correct: list[bool], bins: int = 10) -> dict:
    n = len(conf)
    if not n:
        return {"brier": None, "ece": None, "bins": []}
    brier = sum((c - y) ** 2 for c, y in zip(conf, correct)) / n
    groups: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for c, y in zip(conf, correct):
        groups[min(int(c * bins), bins - 1)].append((c, y))
    table, ece = [], 0.0
    for b in sorted(groups):
        xs = groups[b]
        mc, acc = sum(c for c, _ in xs) / len(xs), sum(y for _, y in xs) / len(xs)
        ece += len(xs) / n * abs(mc - acc)
        table.append({"bin": b, "n": len(xs), "mean_conf": round(mc, 3), "accuracy": round(acc, 3)})
    return {"brier": round(brier, 4), "ece": round(ece, 4), "bins": table}


def score(gold: Sequence[GoldItem], answers: Sequence[Answer], footprint: dict | None = None) -> dict:
    by_id = {a.id: a for a in answers}
    edge_ids = set(load_graph().edges)
    rows = [(g, by_id.get(g.id)) for g in gold]
    correct = [a is not None and is_correct(g, a) for g, a in rows]
    conf = [a.confidence if a else 1.0 for g, a in rows]
    ans = [(g, a) for g, a in rows if a and g.status == "answered"]
    tp_ne = sum(1 for g, a in rows if a and g.status == a.status == "no_evidence")
    pred_ne = sum(1 for _, a in rows if a and a.status == "no_evidence")
    gold_ne = sum(1 for g, _ in rows if g.status == "no_evidence")
    cited = [(set(g.edge_ids), set(a.edge_ids)) for g, a in ans if g.edge_ids]
    tags: dict[str, list[bool]] = defaultdict(list)
    for (g, _), ok in zip(rows, correct):
        for t in g.tags:
            tags[t].append(ok)
    n = len(rows) or 1
    return {
        "n": len(rows),
        "accuracy": round(sum(correct) / n, 4),
        "status_accuracy": round(sum(1 for g, a in rows if a and a.status == g.status) / n, 4),
        "direction_accuracy": round(sum(a.direction == g.direction for g, a in ans) / len(ans), 4) if ans else None,
        "certainty_accuracy": round(
            sum(a.certainty == g.certainty for g, a in ans if g.certainty)
            / max(1, sum(1 for g, _ in ans if g.certainty)),
            4,
        ),  # fmt: skip
        "no_evidence_precision": round(tp_ne / pred_ne, 4) if pred_ne else None,
        "no_evidence_recall": round(tp_ne / gold_ne, 4) if gold_ne else None,
        "edge_precision": round(sum(len(g & a) / len(a) for g, a in cited if a) / len(cited), 4) if cited else None,
        "edge_recall": round(sum(len(g & a) / len(g) for g, a in cited) / len(cited), 4) if cited else None,
        "parse_rate": round(sum(not validate_entry(a.to_json(), edge_ids) for _, a in rows if a) / n, 4),
        "missing": sum(1 for _, a in rows if a is None),
        "calibration": calibration(conf, correct),
        "by_tag": {t: {"n": len(v), "accuracy": round(sum(v) / len(v), 4)} for t, v in sorted(tags.items())},
        "footprint": {k: v for k, v in (footprint or {}).items() if k != "log"},
    }


def run_eval(
    settings: Settings, split: str | None = None, repeat: int = 1, paths: Sequence[Path] | None = None
) -> dict:
    from camoreasoning.pipeline import Pipeline, make_context

    gold = load_devsets(paths, split)
    if not gold:
        return {"n": 0, "note": f"no labelled items in {DEVSETS_DIR} (see ROADMAP: gold dev set)"}
    runs = []
    for _ in range(max(1, repeat)):
        ctx = make_context(settings, out_dir=CACHE_DIR / "eval" / "outputs")
        answers, _ = Pipeline(ctx).run([Question(g.id, g.question) for g in gold])
        runs.append((answers, ctx.llm.meter.summary()))
    result = score(gold, *runs[0])
    if repeat > 1:
        keys = [{a.id: (a.status, a.direction) for a in ans} for ans, _ in runs]
        result["flip_rate"] = round(sum(len({k[g.id] for k in keys}) > 1 for g in gold) / len(gold), 4)
    return result


def save_result(result: dict, name: str | None) -> Path:
    path = (RESULTS_DIR / f"{name}.json") if name else (CACHE_DIR / "eval" / "latest.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
    return path
