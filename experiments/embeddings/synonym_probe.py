"""Offline, 0 calls: score `cessation` vs `embed` on model-reworded questions (ROADMAP 24).

Inputs: experiments/embeddings/synonym_probe/out_K.jsonl (written by a model that saw only the node
wording in in_K.jsonl, told to use different words) and key.jsonl (the nodes' classes; built by
synonym_seeds.py). Per question side and linker: right (links one of the node's classes, directly or
through linked nodes), wrong (links something else) or empty. Embed only differs from cessation where
cessation is empty; that slice is what the table is about. Not used for tuning.

    Needs taxonomy/word_vectors.bin.gz (build_vectors.py).
    bash -c '. scripts/env.sh; "$PY" experiments/embeddings/synonym_probe.py'
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from camoreasoning import registry
from camoreasoning.config import load_settings
from camoreasoning.contracts import Question
from camoreasoning.pipeline import Pipeline, make_context

DIR = Path("experiments/embeddings/synonym_probe")


def grade(side, want: set[str], tax) -> str:
    if side.empty:
        return "empty"
    got = {r.id for r in side.classes} | {lb.class_id for r in side.nodes for lb in tax.classes_of(r.id)}
    return "right" if got & want else "wrong"


def main() -> dict:
    key = {k["id"]: k for k in map(json.loads, (DIR / "key.jsonl").read_text().splitlines())}
    rows = [json.loads(line) for p in sorted(DIR.glob("out_*.jsonl")) for line in p.read_text().splitlines() if line]
    ctx = make_context(load_settings(), out_dir=Path(".cache/energy"))
    p, tax = Pipeline(ctx), ctx.taxonomy
    parsed = [p.parse(Question(r["id"], f"What effect does {r['cause']} have on {r['outcome']}?")) for r in rows]
    frames = {name: registry.get("linker", name).link(parsed, ctx) for name in ("cessation", "embed")}
    tally = {name: Counter() for name in frames}
    flips, detail = Counter(), []
    for i, r in enumerate(rows):
        k = key[r["id"]]
        for kind in ("cause", "outcome"):
            want = set(k[f"{kind}_classes"])
            a, b = (grade(getattr(frames[n][i], kind), want, tax) for n in ("cessation", "embed"))
            tally["cessation"][a] += 1
            tally["embed"][b] += 1
            if a == "empty":
                flips[f"empty -> {b}"] += 1
                got = [c.id for c in getattr(frames["embed"][i], kind).classes]
                detail.append({"id": r["id"], "kind": kind, "orig": k[kind], "asked": r[kind], "want": sorted(want),
                               "embed": b, "got": got})  # fmt: skip
    res = {"n_questions": len(rows), "sides": 2 * len(rows), "cessation": dict(tally["cessation"]),
           "embed": dict(tally["embed"]), "where_cessation_empty": dict(flips), "detail": detail}  # fmt: skip
    Path("experiments/results/embed_synonym_probe.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("n_questions", "sides", "cessation", "embed", "where_cessation_empty")})
    for d in r["detail"]:
        print(f"  {d['embed']:5} {d['asked']!r:40} (orig {d['orig']!r}) want {d['want']} got {d['got']}")
