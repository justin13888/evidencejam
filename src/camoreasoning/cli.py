"""Command line: run | ask | validate | eval | calibrate | profile | probe | taxonomy | devset | annotate."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path

from camoreasoning import registry
from camoreasoning.config import DEVSETS_DIR, RESULTS_DIR, load_settings


def _strategies(pairs: list[str]) -> dict[str, str]:
    out = {}
    for p in pairs:
        stage, sep, name = p.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"-s expects STAGE=NAME, got {p!r}")
        out[stage] = name
    return out


def _check_strategies(strategies: dict[str, str]) -> None:
    """Fail before running on a strategy name nobody registered (e.g. one -s argument holding two pairs)."""
    for stage, name in strategies.items():
        if name not in registry.names(stage):
            raise ValueError(f"no strategy {stage}/{name!r}; have {', '.join(registry.names(stage))}")


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
    a.add_argument("--json", action="store_true", help="print the answers.json entry (+ footprint), not a card")
    v = sub.add_parser("validate", help="check answers.json against the README format")
    v.add_argument("answers", type=Path)
    v.add_argument("--questions", type=Path)
    e = sub.add_parser("eval", help="score on labelled devsets")
    e.add_argument("--split", choices=["dev", "holdout"])
    e.add_argument("--repeat", type=int, default=1)
    e.add_argument("--save", metavar="NAME", help="also write experiments/results/NAME.json")
    e.add_argument("files", nargs="*", type=Path)
    c = sub.add_parser("calibrate", help="fit the calibrator on the gold dev split -> experiments/calibration/")
    c.add_argument("files", nargs="*", type=Path)
    sub.add_parser("profile", help="graph profile -> experiments/results/graph_profile.json")
    sub.add_parser("probe", help="endpoint smoke test: usage, thinking-off, JSON schema, prefix cache, latency")
    t = sub.add_parser("taxonomy", help="offline: build classes + node labels into taxonomy/")
    t.add_argument("--labels-only", action="store_true", help="keep classes.yaml, re-run only the node labeller")
    d = sub.add_parser("devset", help="offline: generate dev questions + gold labels into experiments/devsets/")
    d.add_argument("--build-only", action="store_true", help="only write generated.yaml")
    d.add_argument("--gold-only", action="store_true", help="only label the existing generated.yaml")
    an = sub.add_parser("annotate", help="offline bulk labelling harness (see camoreasoning/annotate.py)")
    an.add_argument("action", choices=["export", "check", "merge", "run", "review-export", "review-import"])
    an.add_argument("task", help="node_labels | questions | gold")
    an.add_argument("--chunk", help="export: items per chunk (default 40); check: only this chunk number")
    an.add_argument("-n", type=int, help="export: number of items (sample); review-export: rows")
    an.add_argument("--seed", type=int, default=0)
    an.add_argument("--workers", type=int, default=4, help="run: parallel chunks")
    an.add_argument("--redo", action="store_true", help="run: also redo chunks that fail check")
    an.add_argument("--stratify", help="review-export: spread the sample over this field's values")
    an.add_argument("--file", type=Path, help="review CSV path (default experiments/annotate/<task>/review.csv)")
    sub.add_parser("strategies", help="list registered strategies per stage")
    args = ap.parse_args(argv)
    try:
        settings = load_settings(strategies=_strategies(args.strategy))
        _check_strategies(dict(settings.strategies))
    except ValueError as err:
        ap.error(str(err))

    if args.cmd == "run":
        from camoreasoning.pipeline import dumps, run_file

        summary = run_file(args.questions, args.answers, settings)
        print(dumps({k: v for k, v in summary.items() if k != "log"}), file=sys.stderr)
        return 0
    if args.cmd == "ask":
        return ask_cmd(" ".join(args.question), settings, args.json)
    if args.cmd == "validate":
        from camoreasoning.answers import load_questions, validate_answers
        from camoreasoning.graph import load_graph

        qids = [q.id for q in load_questions(args.questions)] if args.questions else None
        doc = json.loads(args.answers.read_text(encoding="utf-8"))
        res = validate_answers(doc, set(load_graph().edges), qids)
        print(json.dumps(res, indent=2))
        return 1 if res["errors"] else 0
    if args.cmd == "eval":
        from camoreasoning.evaluate import run_eval, save_result, scorecard

        res = run_eval(settings, args.split, args.repeat, args.files or None)
        path = save_result(res, args.save)
        print(json.dumps(scorecard(res) | {"saved": str(path)} if res.get("n") else res, indent=2))
        return 0
    if args.cmd == "calibrate":
        from camoreasoning.evaluate import run_calibrate

        print(json.dumps(run_calibrate(settings, "dev", args.files or None), indent=2))
        return 0
    if args.cmd == "probe":
        from camoreasoning.llm import probe

        res = probe(settings)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / "endpoint_probe.json").write_text(json.dumps(res, indent=2))
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
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

    settings = offline_settings(settings)
    ctx = make_context(settings)
    get = lambda st: registry.get(st, overrides=settings.strategies)  # noqa: E731
    if args.cmd == "annotate":
        return annotate_cmd(args, ctx)
    if args.cmd == "taxonomy":
        if args.labels_only:
            tax = Taxonomy(dict(ctx.taxonomy.classes), version=ctx.taxonomy.version)
        else:
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

        gen = DEVSETS_DIR / "generated.yaml"
        if args.gold_only:
            items = load_generated(gen)
        else:
            items = get("devset_builder").build(ctx.taxonomy, ctx)
            save_devset(gen, items)
        gold = []
        if not args.build_only:
            labeler = get("gold_labeler")
            gold = labeler.label(items, ctx)
            if gold:
                save_devset(DEVSETS_DIR / f"gold_{labeler.name}.yaml", gold)
        print(json.dumps({"questions": len(items), "labelled": len(gold)}))
        return 0
    return 2


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def ask_cmd(text: str, settings, as_json: bool) -> int:
    """Readable card (or the --json entry). Exit 2 without answering if a side links to nothing.
    Stage exceptions are not caught here: they print a traceback and exit non-zero."""
    from camoreasoning.pipeline import ask_answer, ask_frame, dumps, side_labels, unclear

    t0 = time.perf_counter()
    question = " ".join(text.split())
    p, frame = ask_frame(question, settings)
    ctx, meter = p.ctx, p.ctx.llm.meter
    if (u := unclear(frame, ctx)) is not None:
        msg = unclear_message(u)
        if not frame.cause.text and u["outcome"]["linked"]:  # open cause, e.g. "How do I control X?" (#114)
            from camoreasoning.strategies.parser.assisted import causes_with_evidence

            msg = open_cause_message(u, causes_with_evidence(frame, ctx)) or msg
        foot = {k: v for k, v in meter.summary().items() if k != "log"}
        print(dumps({"id": "ASK", "question": question, "unclear": {"message": msg, **u}, "footprint": foot})
              if as_json else msg)  # fmt: skip
        return 2
    entry, _ = ask_answer(p, frame)
    if as_json:
        print(dumps(entry))
        return 0

    def labels(side) -> str:
        names = side_labels(side, ctx)
        return " / ".join(names[:3]) + (f" (+{len(names) - 3} more)" if len(names) > 3 else "")

    edges = ctx.graph.edges
    studies = {edges[e].get("source_document") for e in entry["edge_ids"] if e in edges} - {None}
    dash = lambda v: "-" if v is None else v  # noqa: E731
    lines = [
        f"Q: {question}",
        f"Linked: {labels(frame.cause)} -> {labels(frame.outcome)} (via {frame.via})",
        f"Answer: {entry['answer']}",
        f"Direction: {dash(entry['direction'])}  Certainty: {dash(entry['certainty'])}  "
        f"Confidence: {entry['confidence']:.2f}",
        f"Cites: {_count(len(entry['edge_ids']), 'edge', 'edges')}, {_count(len(studies), 'study', 'studies')}",
    ]
    if entry.get("searched_for"):
        lines.append(f"Searched for: {entry['searched_for']}")
    lines += [f"Evidence page: {x}" for x in entry.get("extras", [])]
    n_tokens = meter.prompt_tokens + meter.completion_tokens
    lines.append(f"({time.perf_counter() - t0:.1f} s, {meter.calls} LLM calls, {n_tokens} tokens)")
    print("\n".join(lines))
    return 0


def unclear_message(u: dict) -> str:
    """The refusal text for `ask` when a side linked to nothing (see pipeline.unclear)."""

    def read(kind: str) -> str:
        side = u[kind]
        text = f"'{side['text']}'" if side["text"] else "(nothing)"
        return f"{kind} = {text} -> {' / '.join(side['linked'][:3]) or 'nothing'}"

    example = [u[k]["text"] if u[k]["linked"] and u[k]["text"] else f"<{k}>" for k in ("cause", "outcome")]
    found_none = all(not u[k]["text"] and not u[k]["linked"] for k in ("cause", "outcome"))
    lines = [
        "Question isn't clear. We couldn't find a cause and an outcome in your question."
        if found_none
        else f"Question isn't clear: we read {read('cause')}, {read('outcome')}.",
        f"Please rephrase with more context, e.g. 'What effect does {example[0]} have on {example[1]}?'",
    ]
    lines += [f"Nearest {k} classes: {'; '.join(u[k]['suggestions'])}" for k in ("cause", "outcome")
              if u[k]["suggestions"]]  # fmt: skip
    return "\n".join(lines)


def open_cause_message(u: dict, causes: list[tuple[str, int]]) -> str | None:
    """The `ask` reply for a question that names an outcome but no cause; None if no cause has evidence."""
    if not causes:
        return None
    outcome = " / ".join(u["outcome"]["linked"][:3])
    said = f"{u['outcome']['text']} -> {outcome}" if u["outcome"]["text"] else outcome
    listed = ", ".join(f"{label} ({n} {'study' if n == 1 else 'studies'})" for label, n in causes)
    return (
        f"Your question names an outcome ({said}) but no intervention. Interventions with evidence on it: "
        f"{listed}.\nAsk e.g. 'What effect does {causes[0][0]} have on {u['outcome']['linked'][0]}?'"
    )


def offline_settings(settings):
    """Offline commands get a large call budget, the request cache, and ANNOTATE_* endpoint overrides."""
    env = os.environ
    return dataclasses.replace(
        settings,
        max_calls=settings.offline_max_calls,
        llm_cache=True,
        llm_url=env.get("ANNOTATE_URL") or settings.llm_url,
        llm_model=env.get("ANNOTATE_MODEL") or settings.llm_model,
        llm_key=env.get("ANNOTATE_KEY") or settings.llm_key,
    )


def load_generated(path: Path):
    import yaml

    from camoreasoning.contracts import DevQuestion

    if not path.exists():
        raise SystemExit(f"{path} missing: run `camoreasoning devset --build-only` first")
    rows = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("items") or []
    fields = set(DevQuestion.__dataclass_fields__)
    return [DevQuestion(**{k: (tuple(v) if k == "tags" else v) for k, v in r.items() if k in fields}) for r in rows]


def annotate_cmd(args, ctx) -> int:
    from camoreasoning import annotate as A

    if args.task not in A.TASKS:
        print(f"unknown task {args.task}; have {sorted(A.TASKS)}", file=sys.stderr)
        return 2
    review = args.file or (A.task_dir(args.task) / "review.csv")
    if args.action == "export":
        res = A.export(args.task, ctx, int(args.chunk or 40), args.n, args.seed)
    elif args.action == "check":
        res = A.check(args.task, args.chunk)
    elif args.action == "merge":
        res = A.merge(args.task)
    elif args.action == "run":
        res = A.run(args.task, ctx.llm, args.workers, args.redo)
    elif args.action == "review-export":
        res = A.review_export(args.task, review, args.n or 60, args.stratify, args.seed)
    else:
        res = A.review_import(args.task, review)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 1 if res.get("redo") or res.get("errors") else 0
