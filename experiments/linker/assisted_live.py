"""Issue #121 step 1: the live ask.sh path (parser+linker `assisted`, 8 s timeout) on class_gold dev,
one question per pipeline run (as ask.sh does), against the lexical default (0 calls).

Class link: `exact` = each side resolves to exactly the gold class (experiments/devsets/class_seeds.jsonl);
`any` = the gold class is among the linked classes. Needs BRINE_* in the environment (never printed).

    bash -c '. scripts/env.sh; "$PY" experiments/linker/assisted_live.py [--env PATH/.env] [limit]'
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from camoreasoning.config import CACHE_DIR, load_settings
from camoreasoning.contracts import Question
from camoreasoning.evaluate import is_correct, load_devsets, score
from camoreasoning.pipeline import Pipeline, make_context
from camoreasoning.registry import discover

GOLD = Path("experiments/devsets/class_gold.yaml")
SEEDS = Path("experiments/devsets/class_seeds.jsonl")
LIVE = {
    "CAMOREASONING_LLM_TIMEOUT": "8",
    "CAMOREASONING_STRATEGY_PARSER": "assisted",
    "CAMOREASONING_STRATEGY_LINKER": "assisted",
}


def run(gold, env: dict) -> list[dict]:
    settings = load_settings(env)
    rows = []
    for g in gold:
        ctx = make_context(settings, out_dir=CACHE_DIR / "eval" / "outputs")
        t0 = time.perf_counter()
        (a,), (t,) = Pipeline(ctx).run([Question(g.id, g.question)])
        dt = time.perf_counter() - t0
        f = t.frame
        rows.append(
            {
                "id": g.id,
                "answer": a,
                "latency_s": round(dt, 3),
                "calls": ctx.llm.meter.summary().get("calls", 0),
                "via": f.via if f else None,
                "cause": [r.id for r in f.cause.classes] if f else [],
                "outcome": [r.id for r in f.outcome.classes] if f else [],
            }
        )
    return rows


def link(rows, seeds) -> dict:
    out = {}
    for r in rows:
        s = seeds[r["id"].removeprefix("C-")]
        gc, go = s["cause_class"], s["outcome_class"]
        r["link_exact"] = r["cause"] == [gc] and r["outcome"] == [go]
        r["link_any"] = gc in r["cause"] and go in r["outcome"]
        r["paraphrase"] = s["paraphrase"]
    for name, sel in (("all", rows), ("paraphrase", [r for r in rows if r["paraphrase"]])):
        out[name] = {"n": len(sel), "exact": sum(r["link_exact"] for r in sel), "any": sum(r["link_any"] for r in sel)}
    return out


def main() -> int:
    discover()
    args = sys.argv[1:]
    env_file = Path(args.pop(args.index("--env") + 1)) if "--env" in args else None
    args = [a for a in args if a != "--env"]
    limit = int(args[0]) if args else None
    gold = load_devsets([GOLD], split="dev")[:limit]
    seeds = {(d := json.loads(line))["id"]: d for line in SEEDS.read_text().splitlines() if line.strip()}
    base = {k: v for k, v in os.environ.items() if not k.startswith("CAMOREASONING_")}
    if env_file:  # BRINE_* only, values never printed or saved
        for line in env_file.read_text().splitlines():
            k, sep, v = line.strip().removeprefix("export ").partition("=")
            if sep and k.strip().startswith("BRINE_"):
                base[k.strip()] = v.strip().strip("'\"")
    lex_env = {k: v for k, v in base.items() if not k.startswith("BRINE_")}
    report: dict = {}
    by_run = {}
    for name, env in (("lexical", lex_env), ("assisted", {**base, **LIVE})):
        rows = run(gold, env)
        by_run[name] = {r["id"]: r for r in rows}
        s = score(gold, [r["answer"] for r in rows])
        lat = sorted(r["latency_s"] for r in rows)
        report[name] = {
            "n": len(rows),
            "accuracy": s["accuracy"],
            "ece": s["calibration"].get("ece"),
            "calls_total": sum(r["calls"] for r in rows),
            "calls_max": max(r["calls"] for r in rows),
            "calls_per_question": round(sum(r["calls"] for r in rows) / len(rows), 4),
            "latency_mean_s": round(sum(lat) / len(lat), 3),
            "latency_p50_s": lat[len(lat) // 2],
            "latency_max_s": lat[-1],
            "via": {str(v): sum(r["via"] == v for r in rows) for v in {r["via"] for r in rows}},
            "class_link": link(rows, seeds),
        }
        print(name, json.dumps(report[name]), flush=True)
    lx, asd = by_run["lexical"], by_run["assisted"]
    gold_by = {g.id: g for g in gold}
    report["link_regressions"] = [i for i in lx if lx[i]["link_exact"] and not asd[i]["link_exact"]]
    report["link_gains"] = [i for i in lx if asd[i]["link_exact"] and not lx[i]["link_exact"]]
    report["answer_regressions"] = [
        i for i in lx if is_correct(gold_by[i], lx[i]["answer"]) and not is_correct(gold_by[i], asd[i]["answer"])
    ]
    report["answer_gains"] = [
        i for i in lx if is_correct(gold_by[i], asd[i]["answer"]) and not is_correct(gold_by[i], lx[i]["answer"])
    ]
    report["changed_links"] = [
        {
            "id": i,
            "lexical": [lx[i]["cause"], lx[i]["outcome"]],
            "assisted": [asd[i]["cause"], asd[i]["outcome"]],
            "via": asd[i]["via"],
            "calls": asd[i]["calls"],
        }
        for i in lx
        if [lx[i]["cause"], lx[i]["outcome"]] != [asd[i]["cause"], asd[i]["outcome"]]
    ]
    print(json.dumps({k: report[k] for k in ("link_regressions", "link_gains", "answer_regressions", "answer_gains")}))
    if limit is None:
        Path("experiments/results/linker_assisted_live.json").write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
