"""Command line: run | ask | validate | eval | profile | taxonomy | devset. See README."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from camoreasoning import registry
from camoreasoning.config import DEVSETS_DIR, RESULTS_DIR, load_settings


def _strategies(pairs: list[str]) -> dict[str, str]:
    return dict(p.split("=", 1) for p in pairs)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="camoreasoning")
    ap.add_argument("-s", "--strategy", action="append", default=[], metavar="STAGE=NAME",
                    help="override a stage's strategy for this command")  # fmt: skip
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="questions file -> answers.json (+ extras, footprint.json)")
    r.add_argument("questions", type=Path)
    r.add_argument("answers", type=Path)
    a = sub.add_parser("ask", help="answer one free-form question")
    a.add_argument("question", nargs="+")
    v = sub.add_parser("validate", help="check answers.json against the README format")
    v.add_argument("answers", type=Path)
    v.add_argument("--questions", type=Path)
    e = sub.add_parser("eval", help="score on labelled devsets")
    e.add_argument("--split", choices=["dev", "holdout"])
    e.add_argument("--repeat", type=int, default=1)
    e.add_argument("--save", metavar="NAME", help="also write experiments/results/NAME.json")
    e.add_argument("files", nargs="*", type=Path)
    sub.add_parser("profile", help="graph profile -> experiments/results/graph_profile.json")
    sub.add_parser("taxonomy", help="offline: build classes + node labels into taxonomy/")
    sub.add_parser("devset", help="offline: generate dev questions + gold labels into experiments/devsets/")
    sub.add_parser("strategies", help="list registered strategies per stage")
    args = ap.parse_args(argv)
    settings = load_settings(strategies=_strategies(args.strategy))

    if args.cmd == "run":
        from camoreasoning.pipeline import dumps, run_file

        summary = run_file(args.questions, args.answers, settings)
        print(dumps({k: v for k, v in summary.items() if k != "log"}), file=sys.stderr)
        return 0
    if args.cmd == "ask":
        from camoreasoning.pipeline import ask, dumps

        print(dumps(ask(" ".join(args.question), settings)))
        return 0
    if args.cmd == "validate":
        from camoreasoning.answers import load_questions, validate_answers
        from camoreasoning.graph import load_graph

        qids = [q.id for q in load_questions(args.questions)] if args.questions else None
        doc = json.loads(args.answers.read_text(encoding="utf-8"))
        res = validate_answers(doc, set(load_graph().edges), qids)
        print(json.dumps(res, indent=2))
        return 1 if res["errors"] else 0
    if args.cmd == "eval":
        from camoreasoning.evaluate import run_eval, save_result

        res = run_eval(settings, args.split, args.repeat, args.files or None)
        path = save_result(res, args.save)
        print(json.dumps({k: v for k, v in res.items() if k != "calibration"} | {
            "brier": res.get("calibration", {}).get("brier"), "ece": res.get("calibration", {}).get("ece"),
            "saved": str(path)}, indent=2))  # fmt: skip
        return 0
    if args.cmd == "profile":
        from camoreasoning.graph import load_graph
        from camoreasoning.profile import profile_graph

        prof = profile_graph(load_graph())
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / "graph_profile.json").write_text(json.dumps(prof, indent=2, ensure_ascii=False))
        print(json.dumps({k: prof[k] for k in ("counts", "node_degree", "nodes_in_multiple_documents",
                                               "predicate_sign_vs_variable_level")}, indent=2))  # fmt: skip
        return 0
    if args.cmd == "strategies":
        from camoreasoning.config import STAGES

        for st in STAGES:
            print(f"{st}: {', '.join(registry.names(st))}")
        return 0

    from camoreasoning.pipeline import make_context
    from camoreasoning.taxonomy import Taxonomy, save_taxonomy, validate_taxonomy

    ctx = make_context(settings)
    get = lambda st: registry.get(st, overrides=settings.strategies)  # noqa: E731
    if args.cmd == "taxonomy":
        tax = get("taxonomy_builder").build(ctx)
        tax = Taxonomy(tax.classes, tuple(get("node_labeler").label(tax, ctx)), tax.version)
        if errs := validate_taxonomy(tax, set(ctx.graph.nodes)):
            print("\n".join(errs[:20]), file=sys.stderr)
            return 1
        save_taxonomy(tax)
        print(json.dumps({"classes": len(tax.classes), "labels": len(tax.labels),
                          "labelled_nodes": len({lb.node_id for lb in tax.labels}), **ctx.llm.meter.summary()},
                         indent=2, default=str))  # fmt: skip
        return 0
    if args.cmd == "devset":
        from camoreasoning.evaluate import save_devset

        items = get("devset_builder").build(ctx.taxonomy, ctx)
        save_devset(DEVSETS_DIR / "generated.yaml", items)
        labeler = get("gold_labeler")
        gold = labeler.label(items, ctx)
        if gold:
            save_devset(DEVSETS_DIR / f"gold_{labeler.name}.yaml", gold)
        print(json.dumps({"questions": len(items), "labelled": len(gold)}))
        return 0
    return 2
