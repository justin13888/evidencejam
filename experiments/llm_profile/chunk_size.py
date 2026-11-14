"""ROADMAP item 2: how many questions to put in one batched linker call.

Builds template questions from taxonomy synonyms (gold = the class pair), sends the same items through
`LLM.batch_json` at several chunk sizes, and records tokens, latency, missing ids and accuracy.

    bash -c '. scripts/env.sh; "$PY" experiments/llm_profile/chunk_size.py'

Writes experiments/results/llm_chunk_size.json. Cache is off so every call is real.
"""

from __future__ import annotations

import dataclasses
import json
import random
import sys
from pathlib import Path

from camoreasoning.config import RESULTS_DIR, load_settings
from camoreasoning.llm import LLM, LLMError
from camoreasoning.taxonomy import load_taxonomy

N_ITEMS = 50
CHUNKS = (1, 5, 10, 25, 50)
SINGLE_SAMPLE = 5  # chunk=1 costs one call per item, so only sample a few
TOKENS_PER_ITEM = 32
SEED = 7


def build_items(tax) -> list[dict]:
    rng = random.Random(SEED)
    causes = [c for c in tax.of_kind("cause") if c.synonyms]
    outcomes = [c for c in tax.of_kind("outcome") if c.synonyms]
    items = []
    for i in range(N_ITEMS):
        c, o = rng.choice(causes), rng.choice(outcomes)
        cs = rng.choice(c.synonyms).replace("*", "")
        os_ = rng.choice(o.synonyms).replace("*", "")
        items.append({"id": f"q{i}", "q": f"What effect does {cs} have on {os_}?", "gold": (c.id, o.id)})
    return items


def system_prompt(tax) -> str:
    cause = " ".join(c.id for c in tax.of_kind("cause"))
    outcome = " ".join(c.id for c in tax.of_kind("outcome"))
    return (
        "Map each question to one cause class id and one outcome class id, or null if none fits.\n"
        f"CAUSE: {cause}\nOUTCOME: {outcome}\n"
        'Input: one JSON per line {"id","q"}. Reply only JSON: {"<id>": ["<cause_id>", "<outcome_id>"], ...}'
    )


def run(chunk: int, items: list[dict], system: str, settings) -> dict:
    llm = LLM(dataclasses.replace(settings, llm_cache=False, max_calls=len(items)))
    payload = [{"id": it["id"], "q": it["q"]} for it in items]
    try:
        out = llm.batch_json(system, payload, chunk=chunk, tokens_per_item=TOKENS_PER_ITEM, purpose=f"chunk{chunk}")
        error = None
    except LLMError as e:
        out, error = {}, str(e)
    correct = sum(1 for it in items if isinstance(out.get(it["id"]), list) and tuple(out[it["id"]][:2]) == it["gold"])
    m = llm.meter
    n = len(items)
    return {
        "chunk": chunk,
        "items": n,
        "calls": m.calls,
        "failures": m.failures,
        "error": error,
        "missing": n - len(out),
        "accuracy": round(correct / n, 3),
        "prompt_tokens_per_item": round(m.prompt_tokens / n, 1),
        "completion_tokens_per_item": round(m.completion_tokens / n, 1),
        "seconds_per_call": [e["s"] for e in m.log],
        "seconds_per_item": round(sum(e["s"] for e in m.log) / n, 3),
        "usage_reported": all(e.get("usage_reported") for e in m.log),
    }


def main() -> int:
    settings = load_settings()
    if not settings.llm_configured:
        print("BRINE_* not set", file=sys.stderr)
        return 1
    tax = load_taxonomy()
    items = build_items(tax)
    system = system_prompt(tax)
    rows = []
    for chunk in CHUNKS:
        subset = items[:SINGLE_SAMPLE] if chunk == 1 else items
        row = run(chunk, subset, system, settings)
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "seconds_per_call"}), flush=True)
    out = Path(RESULTS_DIR) / "llm_chunk_size.json"
    out.write_text(json.dumps({"model": settings.llm_model, "n_items": N_ITEMS, "rows": rows,
                               "examples": items[:5]}, indent=2))  # fmt: skip
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
