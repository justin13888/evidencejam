"""Run experiments/ask/offtemplate.yaml through ./ask.sh --json against the live endpoint and record
per-question latency, link_via, LLM calls, tokens and linked classes in experiments/ask/results.json.

    python experiments/ask/live.py [--env PATH_TO_.env]

BRINE_* come from the environment, or from --env (sourced by bash, values never printed or saved).
Without them nothing runs and results.json records that the live run was skipped."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from camoreasoning import registry  # noqa: E402
from camoreasoning.config import load_settings  # noqa: E402
from camoreasoning.contracts import Question  # noqa: E402
from camoreasoning.pipeline import ask_frame, make_context  # noqa: E402


def env_with(path: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    if path:
        out = subprocess.run(["bash", "-c", 'set -a; . "$1"; set +a; env -0', "_", str(path)],
                             capture_output=True, check=True)  # fmt: skip
        for kv in out.stdout.split(b"\0"):
            k, _, v = kv.decode().partition("=")
            if k.startswith("BRINE_"):
                env[k] = v
    return env


def lexical_link(question: str, ctx) -> dict:
    """What lexical linking alone gives (0 calls), to tell lexical from LLM wins."""
    p = registry.get("parser").parse(Question("x", question), ctx)
    f = registry.get("linker", "lexical_v2").link([p], ctx)[0]
    return {"cause": [r.id for r in f.cause.classes], "outcome": [r.id for r in f.outcome.classes]}


def live_link(question: str, env: dict[str, str]) -> dict:
    """link_via and classes under ask.sh's settings: a second, in-process parse+link (the --json entry
    does not carry the frame). Costs one more LLM call for questions the linker is unsure about."""
    settings = load_settings({**env, "CAMOREASONING_LLM_TIMEOUT": "8", "CAMOREASONING_STRATEGY_LINKER": "assisted"})
    _, f = ask_frame(question, settings)
    return {
        "via": f.via,
        "cause": [r.id for r in f.cause.classes][:5],
        "outcome": [r.id for r in f.outcome.classes][:5],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", type=Path)
    args = ap.parse_args()
    env = env_with(args.env)
    doc = yaml.safe_load((HERE / "offtemplate.yaml").read_text(encoding="utf-8"))
    out_path = HERE / "results.json"
    if not (env.get("BRINE_URL") and env.get("BRINE_MODEL")):
        if not out_path.exists():  # never overwrite a recorded live run
            out_path.write_text(json.dumps({"live": False, "reason": "BRINE_URL/BRINE_MODEL not set"}) + "\n")
        print("live run skipped: BRINE_URL/BRINE_MODEL not set")
        return 0
    ctx = make_context()
    rows = []
    for it in doc["items"] + doc["unclear"]:
        t0 = time.perf_counter()
        r = subprocess.run([str(ROOT / "ask.sh"), "--json", it["question"]], env=env, cwd=ROOT,
                           capture_output=True, text=True, timeout=120)  # fmt: skip
        dt = time.perf_counter() - t0
        res = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        foot = res.get("footprint", {})
        row = {
            "id": it["id"],
            "question": it["question"],
            "exit": r.returncode,
            "latency_s": round(dt, 2),
            "status": res.get("status") or ("unclear" if "unclear" in res else None),
            "direction": res.get("direction"),
            "calls": foot.get("calls"),
            "tokens": (foot.get("prompt_tokens") or 0) + (foot.get("completion_tokens") or 0),
            "expected": it.get("classes"),
            "link": live_link(it["question"], env),
            "lexical_link": lexical_link(it["question"], ctx),
        }
        if "unclear" in res:
            row["read"] = {k: res["unclear"][k] for k in ("cause", "outcome")}
        rows.append(row)
        print(f"{it['id']}: exit {r.returncode}, {dt:.1f} s, {row['calls']} calls, {row['status']}", flush=True)
    summary = {
        "live": True,
        "n": len(rows),
        "max_latency_s": max(r["latency_s"] for r in rows),
        "over_10s": [r["id"] for r in rows if r["latency_s"] >= 10],
        "nonzero_exit_other_than_2": [r["id"] for r in rows if r["exit"] not in (0, 2)],
        "calls_total": sum(r["calls"] or 0 for r in rows),
        "tokens_total": sum(r["tokens"] for r in rows),
    }
    out_path.write_text(json.dumps({**summary, "rows": rows}, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
