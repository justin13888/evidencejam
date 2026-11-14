"""Render experiments/calibration/reliability.md from the binned calibrator's fitted params.

`camoreasoning calibrate` (frozen evaluate.run_calibrate) writes only <name>.json, so run this after it:

    CAMOREASONING_STRATEGY_CALIBRATOR=binned mise run calibrate
    python experiments/calibration/write_reliability.py [binned.json] [reliability.md]

The table is in-sample (dev rows the calibrator was fitted on); holdout ECE comes from `mise run eval:holdout`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from camoreasoning.config import CALIBRATION_DIR
from camoreasoning.strategies.calibrator.binned import render_reliability_md


def main(argv: list[str]) -> int:
    src = Path(argv[0]) if argv else CALIBRATION_DIR / "binned.json"
    dst = Path(argv[1]) if len(argv) > 1 else src.with_name("reliability.md")
    params = json.loads(src.read_text(encoding="utf-8"))
    dst.write_text(render_reliability_md(params), encoding="utf-8")
    print(dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
