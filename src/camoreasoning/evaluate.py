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
from camoreasoning.contracts import (
    Answer,
    Candidates,
    DevQuestion,
    EdgeVote,
    Frame,
    GoldItem,
    ParsedQuestion,
    Question,
    Side,
    Trace,
)
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
            effects = tuple((str(e), x) for e, x in (it.get("edge_effects") or ()))
            g = GoldItem(**{**it, "edge_ids": tuple(it.get("edge_ids") or ()), "tags": tuple(it.get("tags") or ()),
                            "edge_effects": effects})  # fmt: skip
            if (split is None or g.split == split) and (g.id not in out or g.source.startswith("human")):
                out[g.id] = g
    return list(out.values())


def save_devset(path: Path, items: Sequence[GoldItem | DevQuestion]) -> None:
    rows = []
    for it in items:
        d = asdict(it)
        d = {k: [list(x) if isinstance(x, tuple) else x for x in v] if isinstance(v, tuple) else v
             for k, v in d.items()}  # fmt: skip
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


def score(
    gold: Sequence[GoldItem], answers: Sequence[Answer], footprint: dict | None = None,
    traces: Sequence[Trace] | None = None, settings: Settings | None = None,
) -> dict:  # fmt: skip
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
    tag_status: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    status: dict[str, list[bool]] = defaultdict(list)
    for (g, _), ok in zip(rows, correct):
        status[g.status].append(ok)
        for t in g.tags:
            tags[t].append(ok)
            tag_status[t][g.status].append(ok)
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
        # Per gold status, so a tag that is mostly gold-answered can be compared with answered items only.
        "by_gold_status": _acc_by(status),
        "by_tag": {
            t: {"n": len(v), "accuracy": round(sum(v) / len(v), 4), "by_gold_status": _acc_by(tag_status[t])}
            for t, v in sorted(tags.items())
        },
        "footprint": {k: v for k, v in (footprint or {}).items() if k != "log"},
    } | stage_metrics(gold, traces or (), settings)


def _acc_by(groups: dict[str, list[bool]]) -> dict[str, dict]:
    return {k: {"n": len(v), "accuracy": round(sum(v) / len(v), 4)} for k, v in sorted(groups.items()) if v}


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def stage_metrics(gold: Sequence[GoldItem], traces: Sequence[Trace], settings: Settings | None) -> dict:
    """Per-stage numbers so each owner can measure their own stage (ROADMAP "Owners")."""
    tr = {t.question.id: t for t in traces}
    rec, prec, eff_ok, eff_n = [], [], 0, 0
    for g in gold:
        t = tr.get(g.id)
        if g.status != "answered" or not g.edge_ids or not t or not t.candidates:
            continue
        fwd, ge = set(t.candidates.forward), set(g.edge_ids)
        rec.append(len(fwd & ge) / len(ge))
        if fwd:
            prec.append(len(fwd & ge) / len(fwd))
        votes = {v.edge_id: v for v in (t.verdict.votes if t.verdict else ())}
        for eid, eff in g.edge_effects:
            if eid in votes:
                eff_n += 1
                v = votes[eid]
                eff_ok += (v.effect == eff and v.included) if eff is not None else not v.included
    out = {
        "retrieval_recall": _ratio(sum(rec), len(rec)),
        "retrieval_precision": _ratio(sum(prec), len(prec)),
        "interpreter_effect_accuracy": _ratio(eff_ok, eff_n),
        "interpreter_effect_n": eff_n,
    }
    if settings is not None:
        out["oracle"] = oracle(gold, settings)
    return out


def oracle(gold: Sequence[GoldItem], settings: Settings) -> dict:
    """Aggregator, grader and citer fed the gold edges' effects as votes: isolates them from linker,
    labels, retriever and interpreter. Only answered gold items with edge_effects count.

    Every gold vote is included, unsigned ones (effect None) too: the item is gold-answered, so its edges
    bear on the answer, and an item whose edges are all unsigned is the D2 `unclear` case. Excluding
    them turned those items into no_evidence, which no gold-answered item can be (#61)."""
    from camoreasoning import registry
    from camoreasoning.pipeline import make_context

    items = [g for g in gold if g.status == "answered" and g.edge_effects]
    if not items:
        return {"n": 0}
    ctx = make_context(settings, out_dir=CACHE_DIR / "eval" / "oracle")
    get = lambda st: registry.get(st, overrides=settings.strategies)  # noqa: E731
    agg, grader, citer = get("aggregator"), get("grader"), get("citer")
    d_ok = c_ok = c_n = 0
    eprec, erec = [], []
    for g in items:
        q = Question(g.id, g.question)
        frame = Frame(ParsedQuestion(q, None, None, True), Side(None), Side(None), "none", 0.0)
        cands = Candidates(frame, {}, {}, forward=tuple(e for e, _ in g.edge_effects))
        votes = tuple(
            EdgeVote(e, ctx.graph.edges[e].get("source_document", ""), eff, True, "gold",
                     ctx.graph.edges[e].get("certainty_grade"), ctx.graph.edges[e].get("causal_language"))
            for e, eff in g.edge_effects if e in ctx.graph.edges
        )  # fmt: skip
        verdict = agg.aggregate(votes, cands, ctx)
        d_ok += verdict.direction == g.direction
        cert = grader.grade(verdict, ctx)
        if g.certainty:
            c_n += 1
            c_ok += cert == g.certainty
        cited = set(citer.cite(verdict, ctx)) if verdict.status == "answered" else set()
        ge = set(g.edge_ids)
        if cited:
            eprec.append(len(cited & ge) / len(cited))
        erec.append(len(cited & ge) / len(ge) if ge else 0.0)
    return {
        "n": len(items),
        "direction_accuracy": _ratio(d_ok, len(items)),
        "certainty_accuracy": _ratio(c_ok, c_n),
        "edge_precision": _ratio(sum(eprec), len(eprec)),
        "edge_recall": _ratio(sum(erec), len(erec)),
    }


def scorecard(res: dict) -> dict:
    """The numbers each owner self-evaluates against (targets in ROADMAP "Owners")."""
    fp, cal, orc = res.get("footprint", {}), res.get("calibration", {}), res.get("oracle", {})
    return {
        "A taxonomy+linking": {k: res.get(k) for k in ("retrieval_recall", "retrieval_precision", "status_accuracy",
                                                        "no_evidence_precision", "no_evidence_recall")},
        "B engine": {"direction_accuracy": res.get("direction_accuracy"),
                     "interpreter_effect_accuracy": res.get("interpreter_effect_accuracy"),
                     "certainty_accuracy": res.get("certainty_accuracy"), "edge_precision": res.get("edge_precision"),
                     "edge_recall": res.get("edge_recall"), "oracle": orc},
        "C calibration": {"ece": cal.get("ece"), "brier": cal.get("brier")},
        "D energy+release": {k: fp.get(k) for k in ("calls_per_question", "tokens_per_question")}
        | {"parse_rate": res.get("parse_rate")},
        "overall": {"n": res.get("n"), "accuracy": res.get("accuracy"), "by_gold_status": res.get("by_gold_status"),
                    "by_tag": res.get("by_tag")},
    } | ({"by_file": {name: {k: v for k, v in scorecard(r).items() if k != "D energy+release"}
                      for name, r in res["by_file"].items()}} if res.get("by_file") else {})  # fmt: skip


def run_eval(
    settings: Settings, split: str | None = None, repeat: int = 1, paths: Sequence[Path] | None = None
) -> dict:
    from camoreasoning.pipeline import Pipeline, make_context

    files = list(paths or sorted(DEVSETS_DIR.glob("*.yaml")))
    gold = load_devsets(files, split)
    if not gold:
        return {"n": 0, "note": f"no labelled items in {DEVSETS_DIR} (see ROADMAP: gold dev set)"}
    runs = []
    for _ in range(max(1, repeat)):
        ctx = make_context(settings, out_dir=CACHE_DIR / "eval" / "outputs")
        answers, traces = Pipeline(ctx).run([Question(g.id, g.question) for g in gold])
        runs.append((answers, ctx.llm.meter.summary(), traces))
    answers, footprint, traces = runs[0]
    result = score(gold, answers, footprint, traces, settings)
    if repeat > 1:
        keys = [{a.id: (a.status, a.direction) for a in ans} for ans, _, _ in runs]
        result["flip_rate"] = round(sum(len({k[g.id] for k in keys}) > 1 for g in gold) / len(gold), 4)
    if by_file := score_by_file(files, split, gold, answers, traces, settings):
        result["by_file"] = by_file
    return result


def score_by_file(
    files: Sequence[Path], split: str | None, gold: Sequence[GoldItem], answers: Sequence[Answer],
    traces: Sequence[Trace], settings: Settings,
) -> dict:  # fmt: skip
    """One score per devset file (#50): the sets measure different things (class wording estimates the
    hidden set; node wording stress-tests linking), and a pooled number hides which one a change moved.
    Same run as the pooled score; the footprint is only pooled. Empty when fewer than two files score."""
    out = {}
    for p in files:
        ids = {g.id for g in load_devsets([p], split)}
        if sub := [g for g in gold if g.id in ids]:
            out[Path(p).name] = score(sub, answers, None, traces, settings)
    return out if len(out) > 1 else {}


def run_calibrate(settings: Settings, split: str = "dev", paths: Sequence[Path] | None = None) -> dict:
    """Run the pipeline on gold `split`, hand (Features, correct) rows to the calibrator's `fit`, and
    write experiments/calibration/<name>.json. Never fit on holdout."""
    from camoreasoning import registry
    from camoreasoning.config import CALIBRATION_DIR
    from camoreasoning.pipeline import Pipeline, make_context

    if split == "holdout":
        raise SystemExit("refusing to fit on holdout")
    gold = load_devsets(paths, split)
    if not gold:
        return {"n": 0, "note": "no labelled items"}
    ctx = make_context(settings, out_dir=CACHE_DIR / "eval" / "calibrate")
    answers, traces = Pipeline(ctx).run([Question(g.id, g.question) for g in gold])
    by_id = {a.id: a for a in answers}
    rows = [(t.features, is_correct(g, by_id[g.id])) for g, t in zip(gold, traces) if t.features is not None]
    cal = registry.get("calibrator", overrides=settings.strategies)
    params = cal.fit(rows, ctx)
    if params is None:
        return {"n": len(rows), "calibrator": cal.name, "note": "this calibrator has nothing to fit"}
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    path = CALIBRATION_DIR / f"{cal.name}.json"
    path.write_text(json.dumps(params, indent=2, sort_keys=True))
    return {"n": len(rows), "calibrator": cal.name, "path": str(path)}


def save_result(result: dict, name: str | None) -> Path:
    path = (RESULTS_DIR / f"{name}.json") if name else (CACHE_DIR / "eval" / "latest.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
    return path
