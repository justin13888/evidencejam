"""The honest-limits page (ROADMAP item 20): where the pipeline fails on the holdout, and what it never tries.

Built only from the one holdout pass issue #12 recorded (`experiments/calibration/holdout_report.json`, written
by `experiments/calibration/holdout_report.py`); the holdout is never run again for this page. The page shows:

- failures by trap tag: for every `trap:*` tag on a holdout item, the first `FIRST_N` misses in item-id order,
  unfiltered (whatever the reason for the miss), with the tag's holdout accuracy and the trap inventory's own
  explanation of the trap (`experiments/results/trap_inventory.json`);
- the pooled holdout reliability table, the ECE against its 0.05 target, the constant-0.6 reference, and one line
  per devset file;
- what the pipeline deliberately does not do (multi-hop chains, effect sizes).

`PROVENANCE` states which pipeline that pass measured, because later fixes landed after it. A missing or corrupt
report gives a page that says so; nothing here raises. Static HTML, no script.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

from camoreasoning.components import Context
from camoreasoning.config import CALIBRATION_DIR, RESULTS_DIR
from camoreasoning.strategies import DEFAULTS
from camoreasoning.strategies.calibrator.baseline import CONSTANT
from camoreasoning.strategies.extras.baseline import _page, _rel, _wrap

REPORT = CALIBRATION_DIR / "holdout_report.json"
INVENTORY = RESULTS_DIR / "trap_inventory.json"
PAGE = "limits.html"
FIRST_N = 3  # misses shown per trap tag
BINS = 10
TRAP = "trap:"
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z'])")
PROVENANCE = (
    "The holdout was scored once, for issue #12, on the pipeline as of commit 82fa03d. Three fixes landed after "
    "that pass and are not measured here: #65 (owl survival node relabelled), #68 (linker flips ending causes and "
    "counts unsigned oracle votes) and #69 (wider, more focused retrieval). The holdout was not run again for this "
    "page, so these numbers describe that earlier pipeline. Confidences come from the <code>binned</code> "
    "calibrator fitted on dev; because of the miss below it is not the default calibrator."
)
NON_GOALS = (
    (
        "Multi-hop chains",
        "We answer only from claims that link the asked cause directly to the asked outcome. We never chain "
        "A affects B and B affects C into an answer about A and C: about a third of questions have no direct "
        "evidence, and a chain would turn many of those correct no-evidence answers into false ones.",
    ),
    (
        "Effect sizes",
        "We report the direction (increase, decrease, no effect, mixed or unclear), how certain the evidence is, "
        "and how many studies point each way. We do not say how large an effect is, and we do not pool or "
        "compare magnitudes across studies.",
    ),
)


def shipped(calibrator: str) -> str:
    """One sentence on what confidence this run's answers carry, against what the tables below measured."""
    tables = "the confidences in the tables below come from the <code>binned</code> calibrator measured on the holdout."
    if calibrator == "baseline" and len(set(CONSTANT.values())) == 1:
        const = next(iter(CONSTANT.values()))
        return (
            f'<p class="shipped">The answers in this run all carry confidence {const:g} (the <code>baseline</code> '
            f"calibrator); {tables}</p>"
        )
    return (
        f'<p class="shipped">The answers in this run take their confidence from the <code>{escape(calibrator)}</code> '
        f"calibrator; {tables}</p>"
    )


def load_report(path: Path = REPORT) -> dict | None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) and isinstance(report.get("items"), list) else None


def load_why(path: Path = INVENTORY) -> dict[str, str]:
    """trap tag -> the first sentence of the inventory's explanation (the rest are notes to the team)."""
    try:
        inv = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(inv, dict):
        return {}
    return {
        f"{TRAP}{k}": SENTENCE.split(v["why"].strip(), maxsplit=1)[0]
        for k, v in inv.items()
        if isinstance(v, dict) and isinstance(v.get("why"), str)
    }


def trap_tags(items: list[dict]) -> list[str]:
    return sorted({t for i in items for t in i.get("tags", []) if t.startswith(TRAP)})


def first_misses(items: list[dict], tag: str, n: int = FIRST_N) -> list[dict]:
    """The first n incorrect items carrying tag, in item-id order, whatever the reason they missed."""
    return sorted((i for i in items if tag in i.get("tags", []) and not i.get("correct")), key=lambda i: i["id"])[:n]


def _fmt(x) -> str:
    return "-" if x is None else f"{x:.3f}"


def _answer(a: dict | None) -> str:
    """status, then direction and certainty where answered: 'answered: decrease, low' or 'no evidence'."""
    if not a:
        return "no answer"
    status = str(a.get("status") or "?").replace("_", " ")
    rest = [str(a[k]).replace("_", " ") for k in ("direction", "certainty") if a.get(k)]
    return f"{status}: {', '.join(rest)}" if rest else status


def _summary(items: list[dict], tags: list[str]) -> str:
    rows = []
    for tag in tags:
        tagged = [i for i in items if tag in i.get("tags", [])]
        right = sum(bool(i.get("correct")) for i in tagged)
        rows.append(
            f'<tr><th scope="row"><a href="#{escape(tag.replace(":", "-"))}">{escape(tag[len(TRAP) :])}</a></th>'
            f"<td>{len(tagged)}</td><td>{right}</td><td>{len(tagged) - right}</td>"
            f"<td>{right / len(tagged):.0%}</td></tr>"
        )
    return _wrap(
        "traps-t",
        "Holdout questions per trap tag",
        '<thead><tr><th scope="col">Trap tag</th><th scope="col">Questions</th><th scope="col">Correct</th>'
        '<th scope="col">Missed</th><th scope="col">Accuracy</th></tr></thead><tbody>' + "".join(rows) + "</tbody>",
        "traps",
    )


def _tag_section(items: list[dict], tag: str, why: dict[str, str]) -> str:
    misses = first_misses(items, tag)
    total = sum(1 for i in items if tag in i.get("tags", []) and not i.get("correct"))
    head = f'<h3 id="{escape(tag.replace(":", "-"))}">{escape(tag[len(TRAP) :])}</h3>'
    expl = f"<p>{escape(why[tag])}</p>" if tag in why else ""
    if not misses:
        return f"<section>{head}{expl}<p>No misses on the holdout for this tag.</p></section>"
    rows = "".join(
        f'<tr class="miss"><td>{escape(i["id"])}</td><td>{escape(i.get("question", ""))}</td>'
        f"<td>{escape(_answer(i.get('gold')))}</td><td>{escape(_answer(i.get('predicted')))}</td>"
        f"<td>{'-' if i.get('confidence') is None else format(i['confidence'], '.0%')}</td></tr>"
        for i in misses
    )
    shown = (
        f"the first {len(misses)} of {total} misses"
        if total > len(misses)
        else ("the only miss" if total == 1 else f"all {total} misses")
    )
    table = _wrap(
        f"{escape(tag.replace(':', '-'))}-t",
        f"{escape(tag[len(TRAP) :])}: {shown}, in question-id order",
        '<thead><tr><th scope="col">Id</th><th scope="col">Question</th><th scope="col">Correct answer</th>'
        f'<th scope="col">Our answer</th><th scope="col">Our confidence</th></tr></thead><tbody>{rows}</tbody>',
    )
    return f"<section>{head}{expl}{table}</section>"


def _reliability(report: dict) -> str:
    pooled, base = report.get("pooled") or {}, report.get("baseline_constant") or {}
    cal = pooled.get("calibration") or {}
    ece, target = cal.get("ece"), report.get("target_ece")
    verdict = "meets" if report.get("passes") else "misses"
    by_bin = {b["bin"]: b for b in cal.get("bins", [])}
    rows = []
    for b in range(BINS):
        r = by_bin.get(b, {"n": 0, "mean_conf": None, "accuracy": None})
        rows.append(
            f'<tr class="bin"><th scope="row">{b / BINS:.1f}-{(b + 1) / BINS:.1f}</th><td>{r["n"]}</td>'
            f"<td>{_fmt(r['mean_conf'])}</td><td>{_fmt(r['accuracy'])}</td></tr>"
        )
    files = "".join(
        f'<tr class="file"><th scope="row">{escape(name)}</th><td>{r["n"]}</td><td>{_fmt(r.get("accuracy"))}</td>'
        f"<td>{_fmt(r['calibration']['ece'])}</td><td>{_fmt(r['calibration']['brier'])}</td></tr>"
        for name, r in sorted((report.get("files") or {}).items())
    )
    return (
        f'<p class="ece">On the {pooled.get("n")} holdout questions, accuracy is {_fmt(pooled.get("accuracy"))} and '
        f"expected calibration error (ECE) is <strong>{_fmt(ece)}</strong>, against a target of {target}: it "
        f"<strong>{verdict}</strong> the target. Brier score is {_fmt(cal.get('brier'))}. A constant 0.6 confidence "
        f"on the same answers scores ECE {_fmt(base.get('ece'))} and Brier {_fmt(base.get('brier'))}."
        + (
            ""
            if report.get("passes")
            else " Answers were right less often on the holdout than on the dev questions the calibrator was fitted "
            "on, so the confidence we state runs high."
        )
        + "</p>"
        + _wrap(
            "reliability-t",
            "Holdout reliability: stated confidence against how often the answer was right",
            '<thead><tr><th scope="col">Confidence bin</th><th scope="col">Questions</th>'
            '<th scope="col">Mean confidence</th><th scope="col">Accuracy</th></tr></thead><tbody>'
            + "".join(rows)
            + "</tbody>",
            "reliability",
        )
        + _wrap(
            "files-t",
            "Holdout by devset file",
            '<thead><tr><th scope="col">File</th><th scope="col">Questions</th><th scope="col">Accuracy</th>'
            f'<th scope="col">ECE</th><th scope="col">Brier</th></tr></thead><tbody>{files}</tbody>',
            "files",
        )
    )


def render(report: dict | None, why: dict[str, str], calibrator: str = DEFAULTS["calibrator"]) -> str:
    """The page body. report is holdout_report.json as loaded, or None when it is missing or unreadable.
    calibrator is the one this run's answers used, so the page can say what confidence they carry."""
    non_goals = "".join(f"<h3>{escape(h)}</h3><p>{escape(p)}</p>" for h, p in NON_GOALS)
    tail = f'<h2 id="non-goals">What we deliberately do not do</h2>{non_goals}'
    head = '<h1>Honest limits</h1><p><a href="gapmap.html">Evidence gap map</a></p>' + shipped(calibrator)
    if report is None:
        return head + "<p>The holdout report is missing or unreadable, so no failures are shown.</p>" + tail
    items = report["items"]
    tags = trap_tags(items)
    return (
        head + f"<p>Where the pipeline gets held-out questions wrong, and how far to trust its confidence. "
        f"{PROVENANCE}</p>"
        '<h2 id="failures">Failures by trap tag</h2><p>Each trap is a way the graph can mislead a reader. For each '
        f"tag, the table lists the first {FIRST_N} holdout questions we got wrong, in question-id order, with no "
        "other selection. A question can carry several tags, so it can appear under more than one.</p>"
        + _summary(items, tags)
        + "".join(_tag_section(items, t, why) for t in tags)
        + '<h2 id="reliability">Reliability</h2>'
        + _reliability(report)
        + tail
    )


def write_limits(ctx: Context, report_path: Path = REPORT, inventory_path: Path = INVENTORY) -> str:
    """Write limits.html under ctx.out_dir and return its path as extras writers do."""
    calibrator = (ctx.settings.strategies if ctx.settings else {}).get("calibrator") or DEFAULTS["calibrator"]
    try:
        body = render(load_report(report_path), load_why(inventory_path), calibrator)
    except (KeyError, TypeError, ValueError, AttributeError):  # malformed report: say so rather than raise
        body = render(None, {}, calibrator)
    return _rel(_page(ctx, PAGE, "Honest limits", body))
