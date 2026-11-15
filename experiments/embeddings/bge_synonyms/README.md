# BGE-proposed, audited label-only synonyms (#24 follow-up)

`linker/embed` (#24, GloVe) linked 6 wrong for 1 right on the synonym probe and stays off. This follow-up
asks a stronger embedding model to *propose* taxonomy wording offline, has an auditor decide, and ships
only the audited phrases. Nothing here runs at judging time: no new runtime dependency, 0 LLM calls.

## 1. Model choice (`model_probe.py` → `experiments/results/bge_model_probe.json`)

The 63 probe sides `cessation` leaves empty, scored like `linker/embed` (best cosine over class phrases):

| Model | forced top-1 right | top-3 hit | gap ≥ 0.03: right / wrong | all 160 sides, top-1 right |
|---|---|---|---|---|
| GloVe (#24, its tuned thresholds) | n/a | n/a | 1 / 6 | n/a |
| bge-small-en-v1.5 | 19 | 34 | 12 / 20 | 82 |
| **bge-base-en-v1.5** | 27 | 37 | **21 / 16** | 87 |
| e5-small-v2 | 19 | 40 | 7 / 8 | 80 |
| e5-base-v2 | 28 | 38 | 8 / 10 | 90 |

- BGE-base keeps a usable gap where E5 cosines bunch together, so it is the proposer.
- At ~40% wrong it still cannot link question sides at runtime.
- The gap sweep runs on the same 63 sides, so the numbers are optimistic.

## 2. Candidates (`candidates.py`)

- **Terms:** the free-text `entity_term` of every node on an edge that no class phrase matches: 1137 terms over 1586 nodes.
- **Proposals:** BGE-base gives each term its top 3 classes.
- **Audit:** 8 chunks under `audit/`, decided by Claude (Opus) auditors against `AUDIT.md`.
  - BGE and the earlier LLM labels are hints only.
  - Generic words, near-miss boundaries and already-covered phrases are rejected.
  - Result: 236 of 1137 accepted.

## 3. Apply (`apply.py` → `applied.json`)

- **Dropped automatically (2):** `nh4` and `so2`, under 4 characters.
- **Dropped in a second review (6):** every phrase that changes an existing node label was checked against the old and new labels of those nodes (`REJECT` in `apply.py`).
  - `deer herd reduction*`: a herd reduction would get polarity +1.
  - `reclaimed mine land`, `catch per unit effort` and `species assemblage*`: each swaps a specific class for a generic one.
  - `water flow`: too broad.
  - `hemicryptophyte*`: pushes out the non-native label of "exotic hemicryptophytes".
- **Result:** 213 phrases in `taxonomy/label_synonyms.yaml`; 476 nodes change.
  - 269 keep their class, but it now comes from a phrase match instead of the LLM.
  - 81 had no label before.
  - 126 change class; the second review covered each of them.
  - Labels by source: LLM 1369 → 1050, phrase match 4858 → 5267.
  - 8 nodes with hand fixes in the committed `node_labels.jsonl` are left alone. The script applies a delta instead of a rebuild, because a plain rebuild would also undo those fixes.

## 4. Label-only, not class synonyms

The first version appended the phrases to `curated_classes.yaml`. The linker then matched them on question
sides too. Node-specific wording ("water permanency", "terrain position", "ectomycorrhizal formation")
linked to a whole class, and other studies' edges answered gold `no_evidence` items. Split test, dev split,
0 calls:

| Variant | class dev (83) | node dev (184) |
|---|---|---|
| master | 0.675 | 0.620 |
| phrases as class synonyms (labels + linker) | 0.687 | 0.609 |
| B: linker only (old labels) | 0.675 | 0.603 |
| A: node labels only (linker unchanged) | 0.687 | 0.625 |
| **shipped: A without `hemicryptophyte*`** | **0.687** | **0.630** |

So the phrases live in `taxonomy/label_synonyms.yaml`, which only `node_labeler/curated` reads
(`compile_phrases(taxonomy)`, used by `linker/phrase`, never sees them).

## 5. Result (dev split, 0 calls, defaults unchanged)

| | class dev: acc / ECE / no_evidence P·R / direction | node dev: acc / ECE / no_evidence P·R / direction |
|---|---|---|
| master | 0.675 / 0.075 / 0.91·0.89 / 0.52 | 0.620 / 0.020 / 0.68·0.82 / 0.52 |
| this | **0.687** / 0.087 / **0.94**·0.89 / **0.54** | **0.630** / 0.030 / **0.71**·0.82 / **0.54** |

- Both sets rise (#47 rule), and so does pooled answered accuracy (0.521 → 0.538).
- **ECE** rises by about 0.01 on both sets. It is not refitted here.
- **Probe:** unchanged (63 right / 63 empty / 34 wrong), as expected with the linker untouched.
- **Trap bar (`test_traps.py`):**
  - `near_miss_classes`: 0.5 → 0.75, now above the bar.
  - `negative_subject_qualifiers`: unchanged at 0.5238; the bar rose past it.
  - `unchanged_is_not_null` and `moderators_mediators`: each lose D-Q0061. A root-sucker count is now labelled natural regeneration, and its no-effect vote makes that answer mixed.

## Re-run

```sh
uv venv /tmp/bge && uv pip install -p /tmp/bge/bin/python sentence-transformers PyYAML
PYTHONPATH=src /tmp/bge/bin/python experiments/embeddings/bge_synonyms/candidates.py  # audit/in_*.jsonl
# audit: one agent per chunk, AUDIT.md -> audit/out_*.jsonl
PYTHONPATH=src .venv/bin/python experiments/embeddings/bge_synonyms/apply.py --dry-run  # then without
```
