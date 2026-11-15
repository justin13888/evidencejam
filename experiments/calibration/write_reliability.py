"""Render experiments/calibration/reliability.md from the binned calibrator's fitted params.

`camoreasoning calibrate` (frozen evaluate.run_calibrate) writes only <name>.json, so run this after it:

    CAMOREASONING_STRATEGY_CALIBRATOR=binned mise run calibrate
    python experiments/calibration/write_reliability.py [binned.json] [reliability.md]

The first table is in-sample (dev rows the calibrator was fitted on). When holdout_report.json sits next to the
params (written once by holdout_report.py), its pooled and per-file holdout numbers are appended.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from camoreasoning.config import CALIBRATION_DIR
from camoreasoning.strategies.calibrator.binned import BINS, render_reliability_md


def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.3f}"


def render_holdout_md(report: dict) -> str:
    """Pooled holdout reliability (all BINS bins, empty ones as '-') and one line per devset file."""
    pooled, base = report["pooled"], report["baseline_constant"]
    cal = pooled["calibration"]
    verdict = "passes" if report["passes"] else "misses"
    lines = [
        "",
        f"## Holdout (pooled, out of sample, calibrator `{report['calibrator']}`)",
        "",
        f"rows: {pooled['n']} · accuracy: {_fmt(pooled['accuracy'])} · ECE: {_fmt(cal['ece'])} · "
        f"Brier: {_fmt(cal['brier'])} · target ECE <= {report['target_ece']}: **{verdict}** · "
        f"constant 0.6 on the same answers: ECE {_fmt(base['ece'])}, Brier {_fmt(base['brier'])}",
        "",
        "| confidence bin | n | mean confidence | accuracy |",
        "|---|---:|---:|---:|",
    ]
    by_bin = {b["bin"]: b for b in cal["bins"]}
    for b in range(BINS):
        row = by_bin.get(b, {"n": 0, "mean_conf": None, "accuracy": None})
        lines.append(
            f"| {b / BINS:.1f}-{(b + 1) / BINS:.1f} | {row['n']} | {_fmt(row['mean_conf'])} | {_fmt(row['accuracy'])} |"
        )
    lines += ["", "| devset file | n | accuracy | ECE | Brier |", "|---|---:|---:|---:|---:|"]
    for name, r in sorted(report["files"].items()):
        c = r["calibration"]
        lines.append(f"| {name} | {r['n']} | {_fmt(r['accuracy'])} | {_fmt(c['ece'])} | {_fmt(c['brier'])} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    src = Path(argv[0]) if argv else CALIBRATION_DIR / "binned.json"
    dst = Path(argv[1]) if len(argv) > 1 else src.with_name("reliability.md")
    params = json.loads(src.read_text(encoding="utf-8"))
    text = render_reliability_md(params)
    holdout = src.with_name("holdout_report.json")
    if holdout.exists():
        text += render_holdout_md(json.loads(holdout.read_text(encoding="utf-8")))
    dst.write_text(text, encoding="utf-8")
    print(dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
