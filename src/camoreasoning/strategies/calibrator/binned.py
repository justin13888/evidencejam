"""Hierarchical-shrinkage cell calibrator with an isotonic agreement correction.

In three sentences (for judges): every answer falls in a cell (status x certainty-or-link-route x number of
studies), and its confidence is that cell's dev accuracy, shrunk toward its status's accuracy, which is
itself shrunk toward the global accuracy, so small cells borrow strength from big ones. For answered
questions, a monotone (isotonic) correction then nudges confidence up or down with how strongly the studies
agree, fitted only on what the cells left unexplained and only when there are enough answered rows. The
result is clipped to [0.05, 0.95], because a graph read by heuristics is never certain.

Model (fitted on (Features, was_correct) rows from the gold dev split only, see evaluate.run_calibrate):
  level 0  p0       = (k + M * PRIOR) / (n + M)            global accuracy, anchored to the baseline 0.6
  level 1  p_status = (k + M * p0) / (n + M)                answered / no_evidence
  level 2  p_cell   = (k + M * p_status) / (n + M)          cell = status | sub | n_docs bucket
     sub = certainty for answered (high/moderate/low/very_low), link_via for no_evidence (for no_evidence
     the claim is "the graph has nothing", so how the question was linked is what decides whether the
     search was right); n_docs buckets 0, 1, 2-3, 4+.
  answered only: PAV over `agreement` on residuals (correct - p_cell), pooling on the shrunk block value
     sum(residual) / (n_block + M), so the offsets are monotone and small blocks stay near 0. Skipped
     when fewer than MIN_PAV_ROWS answered rows. n_docs is 0 for every no_evidence row (no included
     votes), so those cells are effectively status | link_via.
  confidence = clip(p_cell + offset(agreement), FLOOR, CEIL); unseen cells fall back to p_status, then p0.

Why M = 4: the dev set has ~100-150 labelled rows spread over ~30 cells, so most cells hold < 5 rows. With
M = 4 a cell needs 4 rows before its own accuracy outweighs its parent, and a 1-row cell moves at most 1/5
of the way from its parent: enough to learn from big cells without letting one lucky row swing a
confidence by 0.4. Fixed (not tuned) so the fit has no free knobs to overfit on a small dev set.
Why residual PAV: certainty and agreement are correlated (mixed verdicts get lower certainty), so a PAV fit
on raw accuracy would double count; on residuals it only adds what the cells missed.

Params: experiments/calibration/binned.json (written by `camoreasoning calibrate`). Missing or corrupt ->
baseline constants and one stderr warning per run. Pure Python, deterministic, 0 LLM calls.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Sequence

from camoreasoning import config
from camoreasoning.components import Calibrator, Context
from camoreasoning.contracts import Features
from camoreasoning.registry import register
from camoreasoning.strategies.calibrator.baseline import CONSTANT

VERSION = 1
M = 4.0  # prior strength (pseudo-rows), see module docstring
PRIOR = 0.6  # level-0 anchor: the baseline constant, so a 0-row fit reproduces baseline
MIN_PAV_ROWS = 20
FLOOR, CEIL = 0.05, 0.95
STATUSES = ("answered", "no_evidence")
BINS = 10
NDIGITS = 6
MEMO_KEY = "calibrator.binned.params"


def clip(x: float) -> float:
    return min(CEIL, max(FLOOR, x))


def docs_bucket(n_docs: int) -> str:
    return "0" if n_docs <= 0 else "1" if n_docs == 1 else "2-3" if n_docs <= 3 else "4+"


def cell_key(f: Features) -> str:
    sub = f.certainty if f.status == "answered" else f.link_via
    return f"{f.status}|{sub or 'none'}|{docs_bucket(f.n_docs)}"


def _shrink(k: float, n: int, parent: float) -> float:
    return (k + M * parent) / (n + M)


def _value(b: dict) -> float:
    return b["sum"] / (b["n"] + M)  # block mean residual, shrunk toward 0 (= the cell estimate)


def _pav(points: list[tuple[float, float]]) -> list[dict]:
    """Isotonic (non-decreasing) regression of residuals on agreement. Ties pooled first, then
    pool-adjacent-violators on the shrunk block values, so the stored offsets themselves are monotone.
    Blocks: lo, hi, n, sum."""
    blocks: list[dict] = []
    for x, r in sorted(points):
        if blocks and blocks[-1]["hi"] == x:
            blocks[-1]["n"] += 1
            blocks[-1]["sum"] += r
        else:
            blocks.append({"lo": x, "hi": x, "n": 1, "sum": r})
    out: list[dict] = []
    for b in blocks:
        out.append(dict(b))
        while len(out) > 1 and _value(out[-2]) > _value(out[-1]):
            b2 = out.pop()
            b1 = out[-1]
            b1["hi"], b1["n"], b1["sum"] = b2["hi"], b1["n"] + b2["n"], b1["sum"] + b2["sum"]
    return out


def _offset(pav: list[dict], agreement: float) -> float:
    """Step function: the last block starting at or below `agreement` (first block below the range)."""
    if not pav:
        return 0.0
    off = pav[0]["offset"]
    for b in pav:
        if b["lo"] <= agreement:
            off = b["offset"]
        else:
            break
    return off


def predict(params: dict, f: Features) -> float:
    status = params["status"].get(f.status, {}).get("estimate", params["global"]["estimate"])
    p = params["cells"].get(cell_key(f), {}).get("estimate", status)
    if f.status == "answered":
        p += _offset(params.get("pav") or [], float(f.agreement))
    return clip(p)


def reliability(conf: Sequence[float], correct: Sequence[bool], bins: int = BINS) -> dict:
    """10 fixed-width bins (all listed, empty ones with n=0), plus ECE and Brier on the same rows."""
    n = len(conf)
    table = []
    ece = 0.0
    for b in range(bins):
        xs = [(c, y) for c, y in zip(conf, correct) if min(int(c * bins), bins - 1) == b]
        if xs:
            mc, acc = sum(c for c, _ in xs) / len(xs), sum(y for _, y in xs) / len(xs)
            ece += len(xs) / n * abs(mc - acc)
        row = {"bin": f"{b / bins:.1f}-{(b + 1) / bins:.1f}", "n": len(xs)}
        row |= {"mean_conf": round(mc, 4), "accuracy": round(acc, 4)} if xs else {"mean_conf": None, "accuracy": None}
        table.append(row)
    brier = sum((c - y) ** 2 for c, y in zip(conf, correct)) / n if n else None
    return {
        "n": n,
        "ece": round(ece, 4) if n else None,
        "brier": round(brier, 4) if brier is not None else None,
        "bins": table,
    }


def render_reliability_md(params: dict) -> str:
    rel = params.get("reliability") or {}
    fmt = lambda x: "-" if x is None else f"{x:.3f}"  # noqa: E731
    lines = [
        "# Reliability (binned calibrator, fitting rows: in-sample)",
        "",
        f"rows: {rel.get('n', 0)} · ECE: {fmt(rel.get('ece'))} · Brier: {fmt(rel.get('brier'))} · "
        f"prior strength M = {params.get('prior_strength')} · PAV: {'on' if params.get('pav') else 'off'}",
        "",
        "| confidence bin | n | mean confidence | accuracy |",
        "|---|---:|---:|---:|",
    ]
    lines += [f"| {b['bin']} | {b['n']} | {fmt(b['mean_conf'])} | {fmt(b['accuracy'])} |" for b in rel.get("bins", [])]
    lines += ["", "| cell (status / certainty or link_via / n_docs) | n | correct | estimate |", "|---|---:|---:|---:|"]
    cells = sorted(params.get("cells", {}).items())
    lines += [f"| {k.replace('|', ' / ')} | {c['n']} | {c['k']} | {c['estimate']:.3f} |" for k, c in cells]
    return "\n".join(lines) + "\n"


def fit_params(rows: Sequence[tuple[Features, bool]]) -> dict:
    rows = list(rows)
    n, k = len(rows), sum(bool(y) for _, y in rows)
    p0 = _shrink(k, n, PRIOR)
    status: dict[str, dict] = {}
    for s in STATUSES:
        ys = [bool(y) for f, y in rows if f.status == s]
        status[s] = {"n": len(ys), "k": sum(ys), "estimate": _shrink(sum(ys), len(ys), p0)}
    counts: dict[str, list[int]] = {}
    for f, y in rows:
        c = counts.setdefault(cell_key(f), [0, 0])
        c[0] += 1
        c[1] += bool(y)
    cells = {
        key: {"n": cn, "k": ck, "estimate": _shrink(ck, cn, status[key.split("|", 1)[0]]["estimate"])}
        for key, (cn, ck) in sorted(counts.items())
    }
    answered = [(f, y) for f, y in rows if f.status == "answered"]
    pav: list[dict] = []
    if len(answered) >= MIN_PAV_ROWS:
        res = [(float(f.agreement), bool(y) - cells[cell_key(f)]["estimate"]) for f, y in answered]
        pav = [
            {"lo": round(b["lo"], NDIGITS), "hi": round(b["hi"], NDIGITS), "n": b["n"],
             "offset": round(_value(b), NDIGITS)}
            for b in _pav(res)
        ]  # fmt: skip
    rnd = lambda d: {**d, "estimate": round(d["estimate"], NDIGITS)}  # noqa: E731
    params = {
        "version": VERSION,
        "model": "hierarchical shrinkage cells + residual PAV on agreement (answered)",
        "prior_strength": M,
        "prior": PRIOR,
        "min_pav_rows": MIN_PAV_ROWS,
        "clip": [FLOOR, CEIL],
        "global": {"n": n, "k": k, "estimate": round(p0, NDIGITS)},
        "status": {s: rnd(v) for s, v in status.items()},
        "cells": {key: rnd(v) for key, v in cells.items()},
        "pav": pav,
    }
    conf = [predict(params, f) for f, _ in rows]
    params["reliability"] = reliability(conf, [bool(y) for _, y in rows])
    params["reliability_md"] = render_reliability_md(params)
    return params


def _valid(p: object) -> bool:
    try:
        assert isinstance(p, dict) and p["version"] == VERSION
        assert all(isinstance(p["status"][s]["estimate"], (int, float)) for s in STATUSES)
        assert isinstance(p["global"]["estimate"], (int, float))
        assert all(isinstance(c["estimate"], (int, float)) for c in p["cells"].values())
        num = (int, float)
        assert all(isinstance(b["lo"], num) and isinstance(b["offset"], num) for b in p.get("pav") or [])
        return True
    except (AssertionError, KeyError, TypeError, AttributeError):
        return False


def load_params(ctx: Context) -> dict | None:
    """Params from experiments/calibration/binned.json, read once per run; None (+ one warning) if unusable."""
    if MEMO_KEY not in ctx.memo:
        path = config.CALIBRATION_DIR / "binned.json"
        params = None
        with contextlib.suppress(OSError, ValueError):
            params = json.loads(path.read_text(encoding="utf-8"))
        if not _valid(params):
            print(f"calibrator/binned: no usable params at {path}; using baseline constants", file=sys.stderr)
            params = None
        ctx.memo[MEMO_KEY] = params
    return ctx.memo[MEMO_KEY]


@register("calibrator", "binned")
class BinnedCalibrator(Calibrator):
    def confidence(self, features: Features, ctx: Context) -> float:
        params = load_params(ctx)
        if params is None:
            return clip(CONSTANT[features.status])
        return predict(params, features)

    def fit(self, rows: Sequence[tuple[Features, bool]], ctx: Context) -> dict | None:
        return fit_params(rows)
