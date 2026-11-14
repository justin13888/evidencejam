"""Fold the auditors' files into experiments/annotate/gold/review.csv so `annotate review-import gold` reads them.

    PYTHONPATH=src python experiments/gold/fold_audit.py --reviewer llm:auditor

Reads experiments/gold/audit/part*_blind.jsonl (the auditor's own label, written before it saw the
model's) and part*_verdicts.jsonl (ok y/n after comparing). For ok = n rows, the human_* columns get the
blind label, in the CSV list format ("ref:effect; ..."; ";" alone = no edges, "null" = empty value).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from camoreasoning import annotate as A

AUDIT = Path(__file__).resolve().parent / "audit"


def read(pattern: str) -> dict[str, dict]:
    return {r["id"]: r for p in sorted(AUDIT.glob(pattern)) for r in A._read_jsonl(p)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviewer", required=True, help='e.g. "llm:auditor"')
    args = ap.parse_args()
    t, path = A.TASKS["gold"], A.task_dir("gold") / "review.csv"
    blind, verdicts = read("part*_blind.jsonl"), read("part*_verdicts.jsonl")
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields, rows = list(reader.fieldnames or []), list(reader)
    done = 0
    for row in rows:
        v = verdicts.get(row["id"])
        if not v:
            continue
        done += 1
        row["ok"], row["reviewer"], row["comment"] = v["ok"], args.reviewer, v.get("comment", "")
        if v["ok"] == "n":
            b = blind[row["id"]]
            for k, spec in t.fields.items():
                val = b.get(k)
                if k == "edges":
                    row[f"human_{k}"] = spec.fmt(val) or ";"
                else:
                    row[f"human_{k}"] = "null" if val is None else spec.fmt(val)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")  # LF, as committed
        w.writeheader()
        w.writerows(rows)
    print(json.dumps({"rows": len(rows), "audited": done, "ok_n": sum(v["ok"] == "n" for v in verdicts.values())}))


if __name__ == "__main__":
    main()
