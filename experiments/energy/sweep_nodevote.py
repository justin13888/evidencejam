"""Dev-only grid over nodevote's thresholds (0 LLM calls). Never run on holdout.

    bash -c '. scripts/env.sh; CAMOREASONING_STRATEGY_LINKER=nodevote "$PY" experiments/energy/sweep_nodevote.py'

Downstream strategies come from the environment, like `mise run eval`.
"""

from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path

from camoreasoning.config import load_settings
from camoreasoning.evaluate import run_eval
from camoreasoning.strategies.linker import nodevote

GRID = {"MODE": ("class", "nodes"), "MIN_SIM": (0.35, 0.45, 0.55), "MIN_SHARE": (0.3, 0.6), "K": (12, 30)}
KEYS = ("accuracy", "status_accuracy", "direction_accuracy", "no_evidence_precision", "no_evidence_recall")


def main() -> list[dict]:
    assert os.environ.get("CAMOREASONING_STRATEGY_LINKER") == "nodevote"
    rows = []
    for vals in itertools.product(*GRID.values()):
        params = dict(zip(GRID, vals, strict=True))
        for k, v in params.items():
            setattr(nodevote, k, v)
        t = time.time()
        r = run_eval(load_settings(), split="dev")
        row = params | {k: r[k] for k in KEYS} | {"ece": r["calibration"]["ece"], "s": round(time.time() - t)}
        rows.append(row)
        print(json.dumps(row), flush=True)
    out = Path("experiments/results/nodevote_sweep.json")
    env = {k: v for k, v in os.environ.items() if k.startswith("CAMOREASONING_STRATEGY_")}
    out.write_text(json.dumps({"env": env, "rows": rows}, indent=1))
    return rows


if __name__ == "__main__":
    main()
