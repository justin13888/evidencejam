"""Organizer-scoring variants as a best/worst range (#94). Eval only: no engine or default changes.

The organizers have not published how correctness, certainty gold, calibration and edges are scored. This
script runs the default pipeline once per split and scores the same answers under each plausible reading,
so a reported number comes with the range it could land in. V1 is the frozen scorer
(`camoreasoning.evaluate.score`, i.e. `mise run eval`) and is asserted equal to it.

Sets: class dev (class_gold.yaml), node dev (gold_annotated.yaml), pooled dev (= `mise run eval`), and
holdout (pooled and per file). Holdout is read-only reporting: nothing here is tuned on it.

    python experiments/scoring_variants/run.py
    -> experiments/results/scoring_variants.{json,md}
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import yaml

from camoreasoning.answers import validate_entry
from camoreasoning.config import CACHE_DIR, DEVSETS_DIR, RESULTS_DIR, load_settings
from camoreasoning.contracts import Answer, GoldItem, Question, Trace
from camoreasoning.evaluate import is_correct, load_devsets, run_eval, score
from camoreasoning.graph import load_graph
from camoreasoning.pipeline import Pipeline, make_context
from camoreasoning.schema import CERTAINTY_ORDER
from camoreasoning.strategies.grader.rubric import ASSOCIATIONAL_PREDICATES, CAP

ROOT = Path(__file__).resolve().parents[2]
FILES = {"class": DEVSETS_DIR / "class_gold.yaml", "node": DEVSETS_DIR / "gold_annotated.yaml"}
LEVELS = sorted(CERTAINTY_ORDER, key=CERTAINTY_ORDER.__getitem__)
FLOOR, PARSE_LIMIT, EMPTY_SHARE = 0.5, 0.05, 1 / 3
V = ("V1", "V2", "V3", "V4")
V_DESC = {
    "V1": "status + direction (current scorer)",
    "V2": "V1 + certainty exact",
    "V3": "V1 + certainty within one ordinal level",
    "V4": "partial credit: mean of status, direction and certainty hits",
    "V2@rule, V3@rule, V4@rule": "the same, with certainty gold from that rule instead of the labelled field",
}
RULES = ("labelled", "D4", "median", "mode", "max", "min")
# Every correctness reading: V1, then V2 to V4 against each certainty-gold rule ("V2" alone = labelled gold).
KEYS = ("V1", *(v if r == "labelled" else f"{v}@{r}" for v in V[1:] for r in RULES))


# --- correctness -------------------------------------------------------------------------------------------
def _cert_hit(gc: str | None, ac: str | None, tol: int) -> bool:
    if gc is None or ac is None:
        return gc == ac
    return abs(CERTAINTY_ORDER[gc] - CERTAINTY_ORDER[ac]) <= tol


def credit(v: str, g: GoldItem, a: Answer | None, gold_cert: str | None) -> float:
    """Correctness of one answer under variant v, in [0, 1]. A missing answer scores 0."""
    if a is None:
        return 0.0
    v1 = is_correct(g, a)
    if v == "V1":
        return float(v1)
    if v in ("V2", "V3"):
        return float(v1 and _cert_hit(gold_cert, a.certainty, 0 if v == "V2" else 1))
    hits = [a.status == g.status]
    if g.status == "answered":
        hits += [a.direction == g.direction, _cert_hit(gold_cert, a.certainty, 0)]
    return sum(hits) / len(hits)


# --- certainty gold ----------------------------------------------------------------------------------------
def gold_certainties(g: GoldItem, edges: dict) -> dict[str, str | None]:
    """Gold certainty recomputed from the gold edges under each candidate rule. `labelled` is the devset's
    own field (labelled with D4); the others read `certainty_grade` off causal_graph.json."""
    out: dict[str, str | None] = {"labelled": g.certainty}
    es = [edges[e] for e in g.edge_ids if e in edges]
    grades = sorted(CERTAINTY_ORDER[e["certainty_grade"]] for e in es if e.get("certainty_grade") in CERTAINTY_ORDER)
    if g.status != "answered" or not grades:
        return out | dict.fromkeys(("D4", "median", "mode", "max", "min"), None if g.status != "answered" else "low")
    lower_median = grades[(len(grades) - 1) // 2]
    drop = g.direction == "mixed" or all(e.get("predicate") in ASSOCIATIONAL_PREDICATES for e in es)
    counts = Counter(grades)
    top = max(counts.values())
    return out | {
        "D4": LEVELS[min(max(lower_median - drop, 0), CERTAINTY_ORDER[CAP])],
        "median": LEVELS[lower_median],
        "mode": LEVELS[min(k for k, c in counts.items() if c == top)],
        "max": LEVELS[grades[-1]],
        "min": LEVELS[grades[0]],
    }


# --- calibration -------------------------------------------------------------------------------------------
def _ece(groups: list[list[tuple[float, float, float]]]) -> float:
    """ECE over bins of (conf, y, weight): weighted |mean conf - mean y| per bin, weighted by bin mass."""
    total = sum(w for xs in groups for _, _, w in xs)
    out = 0.0
    for xs in groups:
        bw = sum(w for _, _, w in xs)
        if bw:
            out += abs(sum(c * w for c, _, w in xs) - sum(t * w for _, t, w in xs)) / total
    return out


def ece_equal_width(conf: list[float], y: list[float], w: list[float], bins: int) -> float:
    groups: dict[int, list] = {}
    for c, t, wi in zip(conf, y, w):
        groups.setdefault(min(int(c * bins), bins - 1), []).append((c, t, wi))
    return _ece(list(groups.values()))


def ece_equal_mass(conf: list[float], y: list[float], w: list[float], bins: int = 10) -> float:
    """Bins of about equal weight, cut only between distinct confidences: tied confidences always share a
    bin, so the result does not depend on item order (with every confidence equal it is |conf - acc|)."""
    by_conf: dict[float, list] = {}
    for c, t, wi in zip(conf, y, w):
        by_conf.setdefault(c, []).append((c, t, wi))
    total, cum, k = sum(w), 0.0, 0
    groups: list[list] = [[]]
    for c in sorted(by_conf):
        groups[-1] += by_conf[c]
        cum += sum(wi for _, _, wi in by_conf[c])
        while k < bins - 1 and cum >= (k + 1) * total / bins:
            k += 1
            if groups[-1]:
                groups.append([])
    return _ece(groups)


def calib(conf: list[float], y: list[float], w: list[float] | None = None) -> dict:
    """Calibration of conf against y; w weights items (default uniform)."""
    eps = 1e-6
    w = w or [1.0] * len(conf)
    total = sum(w)
    clip = lambda p: min(max(p, eps), 1 - eps)  # noqa: E731
    return {
        "ece10": round(ece_equal_width(conf, y, w, 10), 4),
        "ece15": round(ece_equal_width(conf, y, w, 15), 4),
        "ece_mass10": round(ece_equal_mass(conf, y, w), 4),
        "brier": round(sum(wi * (c - t) ** 2 for c, t, wi in zip(conf, y, w)) / total, 4),
        "log_loss": round(
            -sum(wi * (t * math.log(clip(c)) + (1 - t) * math.log(clip(1 - c))) for c, t, wi in zip(conf, y, w))
            / total,
            4,
        ),  # fmt: skip
    }


# --- one set -----------------------------------------------------------------------------------------------
def variants(gold: list[GoldItem], answers: list[Answer], traces: list[Trace], footprint: dict, labels: dict) -> dict:
    edges = load_graph().edges
    by_id = {a.id: a for a in answers}
    tr = {t.question.id: t for t in traces}
    rows = [(g, by_id.get(g.id)) for g in gold]
    gcs = [gold_certainties(g, edges) for g in gold]
    conf = [a.confidence if a else 1.0 for _, a in rows]
    n = len(rows)
    n_empty = sum(g.status == "no_evidence" for g, _ in rows)
    # Weights that give gold-empty items a 1/3 share and answered items the rest.
    w = [(EMPTY_SHARE / n_empty if g.status == "no_evidence" else (1 - EMPTY_SHARE) / (n - n_empty))
         if 0 < n_empty < n else 1 / n for g, _ in rows]  # fmt: skip

    corr = {}
    for k in KEYS:
        v, _, rule = k.partition("@")
        corr[k] = [credit(v, g, a, gc[rule or "labelled"]) for (g, a), gc in zip(rows, gcs)]
    acc = {k: round(sum(ys) / n, 4) for k, ys in corr.items()}
    acc_rw = {k: round(sum(wi * y for wi, y in zip(w, ys)), 4) for k, ys in corr.items()}

    ans = [(g, a, gc) for (g, a), gc in zip(rows, gcs) if a and g.status == "answered"]
    cert_acc = {}
    for r in RULES:
        hits = [a.certainty == gc[r] for _, a, gc in ans if gc[r]]
        cert_acc[r] = round(sum(hits) / max(1, len(hits)), 4)
    d4_agree = [gc["D4"] == g.certainty for g, gc in zip(gold, gcs) if g.status == "answered" and g.certainty]

    cited = [(set(g.edge_ids), set(a.edge_ids)) for g, a, _ in ans if g.edge_ids]
    # Precision divides by every cited gold item (an empty citation scores 0), as `evaluate.score` does.
    p = [len(ge & ae) / len(ae) if ae else 0.0 for ge, ae in cited]
    r = [len(ge & ae) / len(ge) for ge, ae in cited]
    f1 = [2 * len(ge & ae) / (len(ge) + len(ae)) if ae else 0.0 for ge, ae in cited]
    edges_out = {
        "precision": round(sum(p) / len(p), 4) if p else None,
        "recall": round(sum(r) / len(r), 4) if r else None,
        "f1": round(sum(f1) / len(f1), 4) if f1 else None,
        "any_overlap": round(sum(bool(ge & ae) for ge, ae in cited) / len(cited), 4) if cited else None,
        "existence_only": round(sum(bool(ae) for _, ae in cited) / len(cited), 4) if cited else None,
    }

    # Null vs effect: on gold-answered items, does the answer agree on "no effect" vs "some effect"? A
    # no_evidence answer states neither, so it counts as a miss.
    ne = [a.status == "answered" and (g.direction == "no_effect") == (a.direction == "no_effect")
          for g, a, _ in ans if g.direction]  # fmt: skip
    # searched_for names the linked cause and outcome classes (label, case-insensitive), on empty answers.
    sf = []
    for g, a in rows:
        t = tr.get(g.id)
        if not a or a.status != "no_evidence" or not t or not t.frame:
            continue
        sides = [t.frame.cause.classes, t.frame.outcome.classes]
        if all(sides):
            text = (a.searched_for or "").lower()
            sf.append(all(any(labels.get(c.id, c.id).lower() in text for c in s) for s in sides))

    edge_ids = set(edges)
    parse_fail = round(sum(bool(validate_entry(a.to_json(), edge_ids)) for _, a in rows if a) / n, 4)
    calls = (footprint or {}).get("calls_per_question")
    return {
        "n": n,
        "gold_empty_share": round(n_empty / n, 4),
        "correctness": {"raw": acc, "reweighted_empty_1_3": acc_rw},
        "floor_pass": {
            k: {v: x >= FLOOR for v, x in d.items()} for k, d in (("raw", acc), ("reweighted_empty_1_3", acc_rw))
        },  # fmt: skip
        "certainty_gold": {
            "certainty_accuracy": cert_acc,
            "D4_recomputed_agrees_with_label": round(sum(d4_agree) / len(d4_agree), 4) if d4_agree else None,
        },  # fmt: skip
        "calibration": {
            "raw": {k: calib(conf, corr[k]) for k in KEYS},
            "reweighted_empty_1_3": {k: calib(conf, corr[k], w) for k in KEYS},
        },  # fmt: skip
        "edges": edges_out,
        "null_vs_effect_accuracy": round(sum(ne) / len(ne), 4) if ne else None,
        "searched_for_names_classes": {"n": len(sf), "share": round(sum(sf) / len(sf), 4) if sf else None},
        "parse_fail_share": parse_fail,
        "parse_fail_under_5pct": parse_fail < PARSE_LIMIT,
        "calls_per_question": calls,
    }


def run_split(settings, split: str) -> tuple[list[GoldItem], list[Answer], list[Trace], dict]:
    gold = load_devsets(None, split)
    ctx = make_context(settings, out_dir=CACHE_DIR / "eval" / "scoring_variants")
    answers, traces = Pipeline(ctx).run([Question(g.id, g.question) for g in gold])
    return gold, answers, traces, ctx.llm.meter.summary()


def best_worst(res: dict) -> dict:
    """Best and worst value per row family, with which variant gave it."""

    def rng(d: dict, higher: bool = True) -> dict:
        d = {k: v for k, v in d.items() if v is not None}
        lo, hi = min(d, key=d.get), max(d, key=d.get)
        best, worst = (hi, lo) if higher else (lo, hi)
        return {"best": [d[best], best], "worst": [d[worst], worst]}

    acc = {f"{v} {k}": x for k, d in res["correctness"].items() for v, x in d.items()}
    cal = {f"{v} {k}": c for k, d in res["calibration"].items() for v, c in d.items()}
    ece = {f"{m} {v}": c[m] for v, c in cal.items() for m in ("ece10", "ece15", "ece_mass10")}
    return {
        "accuracy": rng(acc) | {"current": res["correctness"]["raw"]["V1"]},
        "floor_pass_all": all(x >= FLOOR for x in acc.values()),
        "floor_fail": sorted(k for k, x in acc.items() if x < FLOOR),
        "certainty_accuracy": rng(res["certainty_gold"]["certainty_accuracy"]),
        "ece": rng(ece, higher=False) | {"current": res["calibration"]["raw"]["V1"]["ece10"]},
        "brier": rng({v: c["brier"] for v, c in cal.items()}, higher=False),
        "log_loss": rng({v: c["log_loss"] for v, c in cal.items()}, higher=False),
        "edges": rng(res["edges"]),
    }


def main() -> None:
    settings = load_settings()
    labels = {c["id"]: c["label"] for c in yaml.safe_load((ROOT / "taxonomy" / "classes.yaml").read_text())["classes"]}
    out: dict = {"variants": V_DESC, "sets": {}}
    for split in ("dev", "holdout"):
        gold, answers, traces, fp = run_split(settings, split)
        sets = {f"pooled_{split}": gold}
        for name, path in FILES.items():
            ids = {g.id for g in load_devsets([path], split)}
            sets[f"{name}_{split}"] = [g for g in gold if g.id in ids]
        for name, sub in sets.items():
            if not sub:
                continue
            res = variants(sub, answers, traces, fp, labels)
            # Sanity: V1 equals the frozen scorer (`mise run eval`).
            ref = score(sub, answers, fp, traces)
            assert res["correctness"]["raw"]["V1"] == ref["accuracy"], (
                name,
                res["correctness"]["raw"]["V1"],
                ref["accuracy"],
            )
            assert res["calibration"]["raw"]["V1"]["ece10"] == ref["calibration"]["ece"], (name, ref["calibration"])
            assert res["calibration"]["raw"]["V1"]["brier"] == ref["calibration"]["brier"], (name, ref["calibration"])
            out["sets"][name] = res | {"range": best_worst(res)}
        # End-to-end: V1 equals what `mise run eval --split <split>` reports, pooled and per file.
        ev = run_eval(settings, split)
        for name, r in [(f"pooled_{split}", ev)] + [
            (f"{k}_{split}", ev.get("by_file", {}).get(p.name)) for k, p in FILES.items()
        ]:
            if r and name in out["sets"]:
                got = out["sets"][name]
                assert (got["correctness"]["raw"]["V1"], got["calibration"]["raw"]["V1"]["ece10"]) == (
                    r["accuracy"],
                    r["calibration"]["ece"],
                ), (name, r["accuracy"], r["calibration"]["ece"])
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "scoring_variants.json").write_text(json.dumps(out, indent=2) + "\n")
    (RESULTS_DIR / "scoring_variants.md").write_text(render(out))
    print(render(out))


def render(out: dict) -> str:
    sets = out["sets"]
    names = list(sets)
    fmt = lambda bw: f"{bw[0]} ({bw[1]})"  # noqa: E731
    lines = [
        "# Organizer-scoring variants (#94)",
        "",
        "Generated by `python experiments/scoring_variants/run.py`. Default pipeline, no engine changes.",
        "V1 is the frozen scorer and equals `mise run eval`. Holdout is reported, never tuned on.",
        "",
        *(f"- **{v}**: {d}" for v, d in out["variants"].items()),
        "- Reweighted: gold-empty items weighted to a 1/3 share, for accuracy and calibration. Floor: accuracy >= 0.5.",
        "- Certainty gold rules: labelled (devset field), D4 recomputed, median, mode, max, min of edge grades.",
        "- ECE: 10 and 15 equal-width bins, 10 equal-mass bins (tied confidences share a bin).",
        "- Ranges span every variant, raw and reweighted. Edge precision matches `evaluate.score`.",
        "- Null-vs-effect: gold-answered items; a no_evidence answer counts as a miss.",
        "",
        "| row | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]

    def row(label: str, f) -> None:
        lines.append(f"| {label} | " + " | ".join(str(f(sets[k])) for k in names) + " |")

    row("n", lambda s: s["n"])
    row("gold empty share", lambda s: s["gold_empty_share"])
    row("accuracy, current (V1)", lambda s: s["range"]["accuracy"]["current"])
    row("accuracy, best", lambda s: fmt(s["range"]["accuracy"]["best"]))
    row("accuracy, worst", lambda s: fmt(s["range"]["accuracy"]["worst"]))
    row("floor holds under every variant", lambda s: s["range"]["floor_pass_all"])
    row("variants below the floor", lambda s: len(s["range"]["floor_fail"]))
    row("certainty accuracy, best", lambda s: fmt(s["range"]["certainty_accuracy"]["best"]))
    row("certainty accuracy, worst", lambda s: fmt(s["range"]["certainty_accuracy"]["worst"]))
    row("D4 recomputed agrees with label", lambda s: s["certainty_gold"]["D4_recomputed_agrees_with_label"])
    row("ECE, current (V1, 10 bins)", lambda s: s["range"]["ece"]["current"])
    row("ECE, best", lambda s: fmt(s["range"]["ece"]["best"]))
    row("ECE, worst", lambda s: fmt(s["range"]["ece"]["worst"]))
    row("Brier, best", lambda s: fmt(s["range"]["brier"]["best"]))
    row("Brier, worst", lambda s: fmt(s["range"]["brier"]["worst"]))
    row("log-loss, best", lambda s: fmt(s["range"]["log_loss"]["best"]))
    row("log-loss, worst", lambda s: fmt(s["range"]["log_loss"]["worst"]))
    row("edges, best", lambda s: fmt(s["range"]["edges"]["best"]))
    row("edges, worst", lambda s: fmt(s["range"]["edges"]["worst"]))
    row("null-vs-effect accuracy", lambda s: s["null_vs_effect_accuracy"])
    row(
        "searched_for names both classes",
        lambda s: f"{s['searched_for_names_classes']['share']} (n={s['searched_for_names_classes']['n']})",
    )
    row("parse-fail share (< 0.05)", lambda s: s["parse_fail_share"])
    row("calls_per_question", lambda s: s["calls_per_question"])
    lines += ["", "## Accuracy per variant (raw / reweighted; * = below the 0.5 floor)", "",
              "| variant | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]  # fmt: skip
    mark = lambda x: f"{x}*" if x < FLOOR else str(x)  # noqa: E731
    for v in KEYS:
        cells = (sets[k]["correctness"] for k in names)
        lines.append(f"| {v} | " + " | ".join(f"{mark(c['raw'][v])} / {mark(c['reweighted_empty_1_3'][v])}"
                                              for c in cells) + " |")  # fmt: skip
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
