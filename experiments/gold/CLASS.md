# Class-level gold (issue #9)

The hidden set asks about broad classes ("What effect does mulch & surface cover have on invasive / non-native
species abundance?"). The node-level set (`gold_annotated.yaml`) does not, so this set drives decisions. The
findings are in `experiments/devsets/AUDIT.md`.

## Result

`experiments/devsets/class_gold.yaml` has 99 items (`C-C0001…`): 83 dev and 16 holdout, 56 answered and
43 `no_evidence` (43%).
- **Blind audit (round 2):** 33/40 (**0.825**). The 7 corrections win at merge. This is accepted below the
  0.85 target; see "Boundary cases".
- **Rubric arithmetic:** D2/D4 recomputed from the labelled edges matches all 99 labels.

## Files

| File | What |
|---|---|
| `experiments/devsets/class_seeds.jsonl` | 99 class-pair seeds (`class_seeds.py`, seed 9) |
| `experiments/annotate/class_questions/` | wording + search terms (labeller output in `out/`) |
| `experiments/devsets/class_generated.yaml` | questions; `meta` has terms, `nominated`, `recall` |
| `experiments/annotate/class_gold/` | candidate chunks, rubric (`PROMPT.md`), round-2 labels, `human.jsonl` |
| `experiments/gold/class_audit/` | round-2 blind audit: sample (seed 47), blind labels, verdicts, `review.csv` |
| `experiments/gold/class_recall/` | recall audit: the 39 round-1 empties searched in `causal_graph.json` |
| `experiments/gold/class_round1/` | superseded round 1: labels, audit (0.775), recall relabel, final yaml |

## How it was built

1. **Seeds.** Class pairs come from `taxonomy/classes.yaml`, stratified by gap-map study count: 57 with
   evidence, 30 empty, 6 near-miss siblings and 6 `time since disturbance`. The taxonomy picks pairs and never
   labels them.
2. **Wording.** `class_questions` shows a labeller each class's label and description, never its synonyms.
   For about half the items (sha1 of the id) it copies the label exactly; otherwise it paraphrases. Either
   way it writes its own search terms. The labeller is Claude; the runtime linker is Qwen.
3. **Candidates** (`class_gold` in `annotate.py`):
   - a taxonomy-free lexical pool over the question and the labeller's terms (top 60);
   - up to 40 edges the taxonomy places between the two classes in either direction;
   - shuffled, then any edges the recall audit found (step 5), appended last.

   The source of each edge is recorded only in `in/*.meta.jsonl`; the labeller never sees it.
4. **Round 1** (in `class_round1/`). Labels used the gold rubric plus a class-membership line. The blind audit
   agreed on 0.775. The disagreements traced to class breadth and to contrasts between two variants of a
   cause.
5. **Recall audit.** Two agents searched the graph directly for all 39 round-1 empties and found edges for 7.
   Those edges became candidates, and 4 of the 7 items turned answered in round 1.
6. **Rubric decisions (Justin, Sat Nov 14), added to `class_gold/PROMPT.md`:**
   - **Strict membership.** An edge counts only if its node is plainly a kind of the class as worded; a better
     fitting neighbour concept is not an instance (water table ≠ soil moisture, plant flowering ≠ breeding
     success, habitat area ≠ fish abundance).
   - **Variant contrasts don't vote.** An edge comparing two kinds of the cause (regime A vs B, subsoil A vs B)
     leaves both arms treated, so it is left out.
7. **Round 2.** Fresh labellers relabelled all 99 items, and a fresh blind audit of 40 (seed 47) agreed on
   33/40. Round 2 changed 25 round-1 labels, mostly toward `no_evidence` under strict membership.

## Boundary cases (accepted, Sat Nov 14)

All 7 round-2 disagreements are calls on class membership; none is arithmetic. The auditor was looser than the
labeller on 4 and stricter on 2:

| Item | Question |
|---|---|
| C0029 | Is seedling stem diameter "basal area"? |
| C0054 | Is manual cutting "competing vegetation" removal, and is functional diversity a "diversity index"? |
| C0003 | Is hatchery share of adult returns "fish numbers"? |
| C0021 | Is mow + burn + glyphosate "prescribed fire"? |
| C0035 | Is the passing of years in a study series "time since disturbance"? |
| C0046 | Is planting beside plots without nurse trees a variant contrast? |
| C0073 | Are submerged plants and bryophytes "native species"? |

## Empty share (accepted, Sat Nov 14)

43% are empty, against about 1/3 in the hidden set. Strict membership turned 15 of the 57 pairs the taxonomy
calls evidenced into `no_evidence`, while gold found evidence for 6 of the 30 pairs the taxonomy calls empty.
The engine reads classes more loosely than gold. Read class results split by the `empty` / `answerable` tags.

## Reproduce

```sh
export PYTHONPATH=src
python experiments/devsets/class_seeds.py
python -m camoreasoning annotate export class_questions --chunk 50   # labelled: out/0001-0002
python -m camoreasoning annotate merge class_questions
python experiments/devsets/class_set.py build                         # adds meta.recall from class_recall/
python -m camoreasoning annotate export class_gold --chunk 10         # labelled: out/0001-0010 (round 2)
rm -f experiments/annotate/class_gold/human.jsonl
python -m camoreasoning annotate merge class_gold
python experiments/gold/fold_audit.py --reviewer llm:auditor --task class_gold \
  --audit-dir experiments/gold/class_audit --csv experiments/gold/class_audit/review.csv
python -m camoreasoning annotate review-import class_gold --file experiments/gold/class_audit/review.csv
python -m camoreasoning annotate merge class_gold
python experiments/devsets/class_set.py gold
python experiments/devsets/class_set.py measure
```

`class_gold/PROMPT.md` is `experiments/annotate/gold/PROMPT.md` plus the class intro and the round-2 rules.
`export` writes it only if it is missing, so keep the committed copy.
