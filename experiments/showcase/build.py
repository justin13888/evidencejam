"""Showcase: a small fixed set of judged-run outputs that exercises every visible part of the report.

Pools the dev split (never the holdout) of class_gold.yaml, then gold_annotated.yaml, plus questions.yaml
through the current defaults, picks one example per visible variant (first matching id, on *our* output),
then runs only those through the judged entry point (`pipeline.run_file`) into outputs/showcase/.
The main outputs/ is never touched.

Writes outputs/showcase/{questions.yaml, answers.json, CATALOG.md, outputs/*.html} and, with --shots, headless
Firefox screenshots (1280 and 320 px, light and dark) under outputs/showcase/shots/. Prints a field-level diff
of the examples against the committed snapshot.json (--update rewrites it). 0 LLM calls unless --ask.

    python experiments/showcase/build.py [--shots] [--update] [--ask "What effect does X have on Y?"]
    python experiments/showcase/build.py --readme   # regenerate the committed README screenshots in docs/img/
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from camoreasoning.answers import load_questions
from camoreasoning.config import OUTPUTS_DIR, ROOT, load_settings
from camoreasoning.contracts import Question
from camoreasoning.evaluate import is_correct, load_devsets
from camoreasoning.pipeline import Pipeline, make_context, run_file
from camoreasoning.strategies.grader.rubric import is_associational

HERE = Path(__file__).parent
SNAPSHOT = HERE / "snapshot.json"
IMG = ROOT / "docs" / "img"  # README screenshots, committed
README_EVIDENCE_ID = "C-C0004"
SHOW = OUTPUTS_DIR / "showcase"
FIELDS = ("status", "direction", "certainty", "confidence", "edge_ids", "answer", "searched_for")
DIRECTIONS = ("increase", "decrease", "mixed", "no_effect", "unclear")


def pool():
    """(question, answer, trace, gold-or-None, source) for every pooled question, under the defaults."""
    files = [ROOT / "experiments/devsets" / f for f in ("class_gold.yaml", "gold_annotated.yaml")]  # class first
    gold = [g for f in files for g in load_devsets([f], split="dev") if g.status]
    qs = [Question(g.id, g.question) for g in gold] + load_questions(ROOT / "questions.yaml")
    golds = {g.id: g for g in gold}
    with tempfile.TemporaryDirectory() as tmp:
        ctx = make_context(load_settings(), out_dir=Path(tmp))
        answers, traces = Pipeline(ctx).run(qs)
        calls = ctx.llm.meter.summary().get("calls", 0)
    rows = [(q, a, t, golds.get(q.id), "dev gold" if q.id in golds else "questions.yaml")
            for q, a, t in zip(qs, answers, traces)]  # fmt: skip
    return rows, ctx, calls


def pick(rows, ctx):
    """Ordered (variant, what-to-look-at, row) picks; each id at most once."""
    used, picks = set(), []

    def take(variant, look, pred, key=None, quiet=False):
        cands = [r for r in rows if r[0].id not in used and pred(r)]
        if key:
            cands.sort(key=key)
        if cands:
            used.add(cands[0][0].id)
            picks.append((variant, look, cands[0]))
        elif not quiet:
            print(f"  (no example for: {variant})", file=sys.stderr)

    def ok(r):
        return r[3] is not None and is_correct(r[3], r[1])

    def studies(r):
        return len(r[2].verdict.doc_effects) if r[2].verdict else 0

    def assoc_only(r):
        inc = r[2].verdict.included if r[2].verdict else ()
        return bool(inc) and all(is_associational(v, ctx) for v in inc)

    answered = [r for r in rows if r[1].status == "answered"]
    for d in DIRECTIONS:
        take(
            f"answered: {d}",
            f"headline verb and hedge for `{d}`; vote table; study list",
            lambda r, d=d: r in answered and r[1].direction == d and (ok(r) or r[3] is None) and not assoc_only(r),
            quiet=True,
        )
        if not picks or picks[-1][0] != f"answered: {d}":  # fall back to any example of that direction
            take(
                f"answered: {d} (gold disagrees)",
                f"`{d}` layout; we disagree with gold",
                lambda r, d=d: r in answered and r[1].direction == d,
            )
    take(
        "associational only", "D1: 'is associated with', never a causal verb", lambda r: r in answered and assoc_only(r)
    )
    take(
        "single study",
        "one-study layout; hedge strength for thin evidence",
        lambda r: r in answered and studies(r) == 1,
    )
    take(
        "most studies",
        "long study list, table width, scrolling at 320 px",
        lambda r: r in answered,
        key=lambda r: -studies(r),
    )
    take(
        "no_evidence: graph has nothing",
        "what we searched for; nearest classes; next step",
        lambda r: r[1].status == "no_evidence" and r[3] is not None and ok(r) and "seed:empty" in r[3].tags,
    )
    take(
        "no_evidence: question not read",
        "refusal reason distinct from 'graph has nothing'",
        lambda r: (
            r[1].status == "no_evidence"
            and r[4] == "questions.yaml"
            and (r[2].frame is None or r[2].frame.cause.empty or r[2].frame.outcome.empty)
        ),
    )
    take(
        "trap we get wrong",
        "honest limits: is the wrong answer visibly hedged?",
        lambda r: r[3] is not None and not ok(r) and any(t.startswith("trap:") for t in r[3].tags),
    )
    take(
        "false no_evidence",
        "an evidenced pair we refuse: does the page still help?",
        lambda r: r[3] is not None and r[3].status == "answered" and r[1].status == "no_evidence",
    )
    take("b4 (practice, known sign issue #101)", "the one answered practice question", lambda r: r[0].id == "b4")
    return picks


def _profile(prof: str, dark: bool) -> None:
    Path(prof, "user.js").write_text(
        f'user_pref("ui.systemUsesDarkTheme", {int(dark)});\n'
        f'user_pref("layout.css.prefers-color-scheme.content-override", {0 if dark else 1});\n'
    )


def _shoot(ff: str, prof: str, page: Path, out: Path, width: int, height: int) -> None:
    cmd = [ff, "--headless", "--profile", prof, "--no-remote", f"--window-size={width},{height}"]
    cmd += ["--screenshot", str(out), page.resolve().as_uri()]
    subprocess.run(cmd, capture_output=True, timeout=60, check=False)


def screenshot(pages: list[Path], shots: Path) -> None:
    ff = shutil.which("firefox")
    if not ff:
        print("firefox not found; skipping --shots", file=sys.stderr)
        return
    shots.mkdir(parents=True, exist_ok=True)
    for scheme, dark in (("light", False), ("dark", True)):
        with tempfile.TemporaryDirectory() as prof:
            _profile(prof, dark)
            for page in pages:
                for width in (1280, 320):
                    _shoot(ff, prof, page, shots / f"{page.stem}.{scheme}.{width}.png", width, 2400)
    print(f"shots: {len(list(shots.glob('*.png')))} png in {shots.relative_to(ROOT)}")


def readme_shots() -> int:
    """Regenerate the README screenshots in docs/img/ (committed) from a fresh run at HEAD's defaults.

    Light scheme, 1280 x 1400, the top of each page: evidence.png is the page of README_EVIDENCE_ID (a mixed,
    two-study class question), gapmap.png and limits.png come from the same run. 0 LLM calls."""
    ff = shutil.which("firefox")
    if not ff:
        print("firefox not found; cannot regenerate docs/img", file=sys.stderr)
        return 1
    gold = {g.id: g for g in load_devsets([ROOT / "experiments/devsets/class_gold.yaml"], split="dev")}
    run = OUTPUTS_DIR / "readme"
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)
    qfile = run / "questions.yaml"
    q = gold[README_EVIDENCE_ID]
    qfile.write_text(yaml.safe_dump({"questions": [{"id": q.id, "question": q.question}]}, sort_keys=False))
    summary = run_file(qfile, run / "answers.json")
    pages = run / "outputs"
    targets = {"evidence": pages / f"{q.id}.html", "gapmap": pages / "gapmap.html", "limits": pages / "limits.html"}
    with tempfile.TemporaryDirectory() as prof:
        _profile(prof, dark=False)
        for name, page in targets.items():
            _shoot(ff, prof, page, IMG / f"{name}.png", 1280, 1400)
    print(f"docs/img: {', '.join(f'{n}.png' for n in targets)} from {q.id} ({summary.get('calls', 0)} LLM calls)")
    return 0


def diff(current: dict, update: bool) -> int:
    old = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}
    changes = []
    for k in sorted(set(old) | set(current)):
        if k not in old or k not in current:
            changes.append(f"  {k}: {'added' if k in current else 'removed'}")
            continue
        for f in FIELDS:
            if old[k].get(f) != current[k].get(f):
                changes.append(f"  {k}.{f}: {old[k].get(f)!r}\n      -> {current[k].get(f)!r}")
    print(f"diff vs {SNAPSHOT.relative_to(ROOT)}: " + ("no changes" if not changes else f"{len(changes)} change(s)"))
    print("\n".join(changes))
    if update or not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(current, indent=1, ensure_ascii=False) + "\n")
        print(f"snapshot written: {SNAPSHOT.relative_to(ROOT)}")
    return len(changes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shots", action="store_true", help="headless Firefox screenshots, light/dark x 1280/320")
    ap.add_argument("--update", action="store_true", help="rewrite snapshot.json from this run")
    ap.add_argument("--ask", metavar="QUESTION", help="also run ./ask.sh on QUESTION (1 LLM call)")
    ap.add_argument("--readme", action="store_true", help="only regenerate the README screenshots in docs/img/")
    args = ap.parse_args()
    if args.readme:
        return readme_shots()

    rows, ctx, pool_calls = pool()
    picks = pick(rows, ctx)
    if SHOW.exists():
        shutil.rmtree(SHOW)
    SHOW.mkdir(parents=True)
    qfile = SHOW / "questions.yaml"
    qfile.write_text(yaml.safe_dump({"questions": [{"id": r[0].id, "question": r[0].text} for _, _, r in picks]},
                                    sort_keys=False, allow_unicode=True, width=1000))  # fmt: skip
    summary = run_file(qfile, SHOW / "answers.json")
    out = json.loads((SHOW / "answers.json").read_text())["answers"]
    by_id = {a["id"]: a for a in out}
    pages_dir = SHOW / "outputs"

    lines = ["# Showcase catalog", "",
             f"Generated by `experiments/showcase/build.py` from the defaults; {len(picks)} examples, "
             f"{summary.get('calls', 0)} LLM calls in the showcase run, {pool_calls} in the pooling run.", "",
             "Site pages: [index](outputs/index.html) · [gap map](outputs/gapmap.html) · "
             "[gap cells](outputs/gapcells.html) · [limits](outputs/limits.html)", "",
             "| # | Variant | id | Ours (dir / cert / conf) | Gold | Page | Look at |",
             "|---|---|---|---|---|---|---|"]  # fmt: skip
    for i, (variant, look, (q, _, _, g, src)) in enumerate(picks, 1):
        a = by_id[q.id]
        ours = a["status"]
        if ours == "answered":
            ours = f"{a['direction']} / {a['certainty']} / {a['confidence']}"
        gold = "—" if g is None else (g.status if g.status == "no_evidence" else f"{g.direction} / {g.certainty}")
        page = " ".join(f"[page]({Path(x).relative_to('outputs/showcase').as_posix()})" for x in a.get("extras", []))
        lines.append(f"| {i} | {variant} | `{q.id}` ({src}) | {ours} | {gold} | {page} | {look} |")
    lines += ["", "## Questions and answers", ""]
    for i, (variant, _, (q, *_)) in enumerate(picks, 1):
        a = by_id[q.id]
        lines += [f"**{i}. {variant}: `{q.id}`**: {' '.join(q.text.split())}", "", f"> {a['answer']}", ""]
        if a.get("searched_for"):
            lines += [f"Searched for: {a['searched_for']}", ""]
    (SHOW / "CATALOG.md").write_text("\n".join(lines) + "\n")
    print(f"showcase: {len(picks)} examples -> {(SHOW / 'CATALOG.md').relative_to(ROOT)} "
          f"(calls: pool {pool_calls}, showcase {summary.get('calls', 0)})")  # fmt: skip

    if args.ask:
        subprocess.run([str(ROOT / "ask.sh"), args.ask], cwd=ROOT, check=False, env=os.environ.copy())

    if args.shots:
        pages = [ROOT / x for a in out for x in a.get("extras", [])]
        pages += [pages_dir / f"{n}.html" for n in ("index", "gapmap", "gapcells", "limits")]
        if args.ask:
            pages += [OUTPUTS_DIR / "ask" / "ASK.html"]
        screenshot([p for p in dict.fromkeys(pages) if p.exists()], SHOW / "shots")

    diff({a["id"]: {f: a.get(f) for f in FIELDS} for a in out}, args.update)
    return 0


if __name__ == "__main__":
    sys.exit(main())
