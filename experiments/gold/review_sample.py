"""ROADMAP item 10: draw the gold audit sample stratified by trap tag, in `annotate review-export` CSV format.

    PYTHONPATH=src python experiments/gold/review_sample.py [-n 40] [--seed 10]

`annotate review-export --stratify` groups on a top-level field of the merged row, but trap tags live in
`_meta.tags`, so this script does the sampling and reuses annotate's own column formatting. The CSV it
writes (experiments/annotate/gold/review.csv) is read back by `annotate review-import gold` unchanged.

It also writes `blind.jsonl` next to it: id, question and candidate edges only, no model label. The
auditor labels from that file first, then opens the CSV to compare (see experiments/gold/AUDIT.md).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict

from camoreasoning import annotate as A


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=10)
    args = ap.parse_args()
    t, d = A.TASKS["gold"], A.task_dir("gold")
    items = {it["id"]: it for c in A.chunks("gold") for it in A._read_jsonl(d / "in" / f"{c}.jsonl")}
    rows = [r for r in A.merged("gold") if r["id"] in items]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:  # an item joins the group of its rarest tag, so small traps are not crowded out
        groups[min(r["_meta"].get("tags") or ["untagged"], key=lambda g: sum(g in (x["_meta"].get("tags") or [])
                                                                              for x in rows))].append(r)  # fmt: skip
    rng = random.Random(args.seed)
    pick, per = [], max(1, args.n // len(groups))
    for g in sorted(groups):
        pick += rng.sample(groups[g], min(per, len(groups[g])))
    left = [r for r in rows if r not in pick]
    pick += rng.sample(left, max(0, min(args.n - len(pick), len(left))))
    names = list(t.fields)
    with open(d / "review.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "context", *[f"model_{k}" for k in names], "model_note", "ok", *[f"human_{k}" for k in names],
                    "reviewer", "comment"])  # fmt: skip
        for r in pick:
            inv = {v: k for k, v in (r.get("_meta") or {}).get("refs", {}).items()}
            edges = [{"ref": inv.get(x["id"], x["id"]), "effect": x["effect"]} for x in r.get("edges") or []]
            shown = {**r, "edges": edges}
            w.writerow([r["id"], A._describe(items[r["id"]]), *[t.fields[k].fmt(shown.get(k)) for k in names],
                        r.get("note", ""), "", *[""] * len(names), "", ""])  # fmt: skip
    A._write_jsonl(d / "blind.jsonl", ({"id": r["id"], "question": items[r["id"]]["question"],
                                        "candidates": items[r["id"]]["candidates"]} for r in pick))  # fmt: skip
    tags = defaultdict(int)
    for r in pick:
        for g in r["_meta"].get("tags") or ["untagged"]:
            tags[g] += 1
    print(json.dumps({"rows": len(pick), "by_tag": dict(sorted(tags.items())), "csv": str(d / "review.csv")}))


if __name__ == "__main__":
    main()
