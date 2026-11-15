"""Model choice for candidates.py: BGE / E5 vs GloVe on the #24 synonym probe (offline, not a runtime dependency).

Same class scoring as linker/embed: a class's score is its best cosine over its phrases (label, label parts
split on & / , ( and synonyms with * removed), restricted to the side's kind. Reports:
  - empty63: the 63 sides `cessation` leaves empty (glove_probe.json detail), the slice an embedding fallback
    would touch. Forced top-1 / top-3, then a sweep over the top-1 vs runner-up gap (linked right / wrong).
  - all160: forced top-1 over every reworded side (model quality alone, ignoring the lexical linker).

Run in the separate venv described in candidates.py, from the repo root:

    /tmp/bge/bin/python experiments/embeddings/bge_synonyms/model_probe.py

Writes experiments/results/bge_model_probe.json.
"""

import json
import re
import time
from pathlib import Path

import yaml
from sentence_transformers import SentenceTransformer

PROBE = Path("experiments/embeddings/synonym_probe")
OUT = Path("experiments/results/bge_model_probe.json")
MODELS = {
    "bge-small-en-v1.5": ("BAAI/bge-small-en-v1.5", ""),
    "bge-base-en-v1.5": ("BAAI/bge-base-en-v1.5", ""),
    "e5-small-v2": ("intfloat/e5-small-v2", "query: "),
    "e5-base-v2": ("intfloat/e5-base-v2", "query: "),
}
GAPS = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10]

classes = yaml.safe_load(Path("taxonomy/classes.yaml").read_text())["classes"]
phr = []  # (class id, kind, phrase)
for c in classes:
    parts = [p.strip() for p in re.split(r"[&/,()]", c["label"]) if p.strip()]
    for p in dict.fromkeys([c["label"], *parts, *(s.replace("*", "").strip() for s in c.get("synonyms") or [])]):
        if p:
            phr.append((c["id"], c["kind"], p))

key = {k["id"]: k for k in map(json.loads, (PROBE / "key.jsonl").read_text().splitlines())}
rows = [json.loads(x) for f in ("out_1.jsonl", "out_2.jsonl") for x in (PROBE / f).read_text().splitlines() if x]
all160 = [(r[k], k, set(key[r["id"]][f"{k}_classes"])) for r in rows for k in ("cause", "outcome")]
glove = json.loads(Path("experiments/results/embed_synonym_probe.json").read_text())
empty63 = [(d["asked"], d["kind"], set(d["want"])) for d in glove["detail"]]
assert len(empty63) == 63, len(empty63)


def rank(model, prefix, sides):
    pv = model.encode([prefix + p for _, _, p in phr], normalize_embeddings=True, batch_size=64)
    sv = model.encode([prefix + t for t, _, _ in sides], normalize_embeddings=True, batch_size=64)
    sims = sv @ pv.T
    out = []
    for i, (_, kind, _) in enumerate(sides):
        best = {}
        for j, (cid, k, _) in enumerate(phr):
            if k == kind and sims[i, j] > best.get(cid, -9):
                best[cid] = float(sims[i, j])
        out.append(sorted(((s, c) for c, s in best.items()), reverse=True))
    return out


res = {
    "phrases": len(phr),
    "glove_pr72": {
        "empty63_linked_right": glove["where_cessation_empty"].get("empty -> right", 0),
        "empty63_linked_wrong": glove["where_cessation_empty"].get("empty -> wrong", 0),
    },
}
for name, (hf, prefix) in MODELS.items():
    t0 = time.time()
    m = SentenceTransformer(hf, device="cpu")
    load = time.time() - t0
    t0 = time.time()
    r63, r160 = rank(m, prefix, empty63), rank(m, prefix, all160)
    enc = time.time() - t0
    top1 = sum(r[0][1] in w for r, (_, _, w) in zip(r63, empty63))
    top3 = sum(any(c in w for _, c in r[:3]) for r, (_, _, w) in zip(r63, empty63))
    sweep = []
    for g in GAPS:
        right = wrong = 0
        for r, (_, _, w) in zip(r63, empty63):
            if r[0][0] - r[1][0] >= g:
                right += r[0][1] in w
                wrong += r[0][1] not in w
        sweep.append({"gap": g, "right": right, "wrong": wrong, "empty": 63 - right - wrong})
    res[name] = {
        "empty63_forced_top1_right": top1,
        "empty63_top3_hit": top3,
        "gap_sweep": sweep,
        "all160_forced_top1_right": sum(r[0][1] in w for r, (_, _, w) in zip(r160, all160)),
        "examples": [
            {
                "asked": t,
                "want": sorted(w),
                "top1": r[0][1],
                "cos": round(r[0][0], 3),
                "gap": round(r[0][0] - r[1][0], 3),
            }
            for r, (t, _, w) in zip(r63, empty63)
        ],
        "load_s": round(load, 1),
        "encode_s": round(enc, 2),
    }
    print(name, {k: v for k, v in res[name].items() if k not in ("examples", "gap_sweep")}, flush=True)
    for s in sweep:
        print("   ", s)
OUT.write_text(json.dumps(res, indent=1))
