# Class-level gold (issue #9)

The hidden set asks about broad classes ("What effect does mulch & surface cover have on invasive / non-native
species abundance?"). The node-level set (`gold_annotated.yaml`) does not, so this set exists to drive
decisions. The findings are in `experiments/devsets/AUDIT.md`.

## Files

| File | What |
|---|---|
| `experiments/devsets/class_seeds.jsonl` | 99 class-pair seeds (`class_seeds.py`, seed 9) |
| `experiments/annotate/class_questions/` | wording + search terms (labeller output in `out/`) |
| `experiments/devsets/class_generated.yaml` | questions; `meta` has terms, `nominated`, `recall` |
| `experiments/annotate/class_gold/` | candidate chunks, rubric (`PROMPT.md`), labels, `human.jsonl` |
| `experiments/gold/class_audit/` | blind audit: sample, blind labels, verdicts, `review.csv` |
| `experiments/gold/class_recall/` | recall audit (`found_part*.jsonl`) and the blind relabel of flagged items |
| `experiments/devsets/class_gold.yaml` | final gold, ids `C-C0001…`, 83 dev / 16 holdout |

## How it was built

1. **Seeds.** Class pairs come from `taxonomy/classes.yaml`, stratified by gap-map study count: 57 with
   evidence, 30 empty, 6 near-miss siblings and 6 `time since disturbance`. The taxonomy is used to pick
   pairs, never to label them.
2. **Wording.** `class_questions` shows a labeller each class's label and description, never its synonyms.
   For about half the items (sha1 of the id) it copies the label exactly; otherwise it paraphrases. Either
   way it writes its own search terms. The labeller is Claude; the runtime linker is Qwen.
3. **Candidates.** `class_gold` (in `annotate.py`) builds a taxonomy-free lexical pool from the question and
   the labeller's terms (top 60), adds up to 40 edges the taxonomy places between the two classes in either
   direction, and shuffles them. The source of each edge is recorded only in `in/*.meta.jsonl`.
4. **Labels.** One `labeler` per chunk of 10, using `class_gold/PROMPT.md`: the round-2 gold rubric (including
   the D3 null rule) plus a class-membership line.
5. **Recall audit.** Two agents searched `causal_graph.json` directly for all 39 `no_evidence` items and found
   edges for 7. Those edges were appended to the items' candidates (earlier refs unchanged). A fresh labeller
   relabelled the 7 items blind. Its labels win, and 4 changed to answered.
6. **Blind audit.** 40 items, sampled stratified with seed 31 (`review_sample.py --task class_gold`). The
   result was **31/40 (0.775)**, against a target of 0.85. The 9 corrections win at merge.

## Open questions for the rubric owner

- **Variant-vs-variant contrasts.** Are contrasts between two kinds of the cause (regime A vs regime B)
  evidence for "what does the cause do"? The labeller and auditor split on this (C0032, C0087).
- **Class breadth.** Should neighbouring classes stay strict? The cases in dispute: water table vs soil
  moisture (C0018), moss-layer transfer vs rewetting (C0041), plant flowering vs breeding success (C0044,
  kept as answered by the recall relabel), and fish habitat area vs fish abundance (C0056, kept as
  no_evidence).

## Reproduce

```sh
export PYTHONPATH=src
python experiments/devsets/class_seeds.py
python -m camoreasoning annotate export class_questions --chunk 50   # labelled: out/0001-0002
python -m camoreasoning annotate merge class_questions
python experiments/devsets/class_set.py build                         # adds meta.recall from class_recall/
python -m camoreasoning annotate export class_gold --chunk 10         # labelled: out/0001-0010
python -m camoreasoning annotate merge class_gold
rm experiments/annotate/class_gold/human.jsonl
python experiments/gold/fold_audit.py --reviewer llm:auditor --task class_gold \
  --audit-dir experiments/gold/class_audit --csv experiments/gold/class_audit/review.csv
python -m camoreasoning annotate review-import class_gold --file experiments/gold/class_audit/review.csv
python -m camoreasoning annotate review-import class_gold --file experiments/gold/class_recall/review_recall.csv
python -m camoreasoning annotate merge class_gold
python experiments/devsets/class_set.py gold
python experiments/devsets/class_set.py measure
```

`class_gold/PROMPT.md` is `experiments/annotate/gold/PROMPT.md` with the class intro lines. `export` writes it
only if it is missing, so keep the committed copy.
