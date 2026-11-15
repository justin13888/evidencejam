# Gold dev set audit (issue #9, Sat Nov 14)

This audit checks whether `experiments/devsets/` can be trusted for tuning and for flipping defaults. It covers
the state after PR #35 (questions) and PR #37 (gold), the fixes made on this branch, and what is still open.
Every number below can be recomputed with the commands at the end.

## Verdict

| | Before (PRs #35, #37) | After |
|---|---|---|
| Node-level set (`gold_annotated.yaml`) | 178 items, 44% empty, 8 short trap tags, D3 conflict | 236 items, 33% empty, inventory trap keys, D3 fixed |
| Class-level set (`class_gold.yaml`) | none | 99 items, 43% empty, 50% paraphrased, recall-audited, audit 0.825 |
| Represents the hidden set? | No (node-level wording) | Yes: the class set uses hidden-set wording, so use it for decisions |

- **Trust the node-level set** for engine and oracle checks. It is the larger set and is audited at 0.925 and
  0.94. Its end-to-end accuracy is a linking stress test, not a hidden-set estimate.
- **Trust the class-level set** for default flips. Its round-2 blind audit agreed on 33/40 (0.825), below the
  0.85 target. All 7 disagreements are class-boundary calls, and this was accepted on Sat Nov 14 (see
  `experiments/gold/CLASS.md`).

## What held (verified)

- **Splits.** Holdout is `sha1(id) % 5 == 0` on the seed id. Recomputing it matches every item in both sets.
  `run_calibrate` refuses to fit on holdout.
- **Seeds.** No random-pair seed has a direct subject → object edge. Every reverse-asked item is gold
  `no_evidence`.
- **Rubric arithmetic.** D2/D4 recomputed mechanically from each item's edges, effects, studies and grades
  (`class_set.py measure`) matches the labelled status, direction and certainty on **236/236 node items and
  99/99 class items**. The labels are internally consistent; the open question is only which edges count.

## Findings and fixes

1. **The node-level set did not represent the hidden set.** Its questions use node wording ("winter road
   clearance → surface elevation"). 67 of 79 answered dev items linked no class on both sides, so dev accuracy
   barely measured the engine. PR #35 ticked "paraphrased class names", but the set had none.
   **Fix:** the class-level set below.
2. **D3 contradicted the schema.** The rubric dropped every edge whose cause is `unchanged`, including real
   nulls (`negated: true`). The schema encodes nulls only as negated, never through `unchanged`.
   **Fix:** `experiments/annotate/gold/PROMPT.md` now says a null votes 0 whatever the node qualifiers say.
   - 27 items whose candidates hold such a null (or whose notes mention it) were relabelled blind in a fresh
     session (`experiments/gold/d3_relabel.py`).
   - Only changes that the rule itself caused were applied: **D-Q0022 and D-Q0025** (no_evidence → no_effect),
     and **D-Q0028 and D-Q0069** (gain a null edge).
   - 3 other differences (D-Q0005, Q0013, Q0079) were judgement calls, not the rule, so they were left as they
     were.
3. **The empty share was 44%** against a target of about 1/3 (55 of 60 random pairs were empty).
   **Fix:** 60 new forward edge seeds (`extend_questions.py`, chunk 0006). 58 survived deduplication, and
   57 are answered. The share is now 78/236 (33.1%), with dev at 62/184 (33.7%).
4. **Trap tags did not match the inventory keys**, and 3 keys had no items.
   **Fix:** `strategies/devset_builder/_traps.py` renames the short tags and derives `comparator_reference`,
   `time_as_cause`, `one_study_many_edges` and `negative_predicates_double_negation` from the seed edge
   (graph fields only). `near_miss_classes` comes from the class set. Every inventory key named in #9 now
   has ≥ 5 dev items across the two files.
5. **Gold candidate recall.** Node-level gold uses a lexical top-60 prefilter. The labeller wrote "candidates
   incomplete" on 4 empties (Q0101, Q0121, Q0122, Q0162). These are **not re-checked**; treat them as
   possible false empties.
6. **Holdout contamination.** Holdout item D-Q0095 is a strict-xfail engine test
   (`tests/strategies/test_gold_disagreements.py`). Node holdout accuracy is 0.346 with it and 0.353 without
   it. Keep it out of any engine fix aimed at that test.
7. **Seed edge not used.** In 7 answered items (Q0027, 28, 61, 65, 68, 69, 81) the labeller judged the seed
   edge irrelevant. Each has a note, and none was overturned by an audit.
8. **Prompt drift (not changed).** `PROMPTS["questions"]` in `annotate.py` still lacks the "be broad" rule from
   `experiments/annotate/questions/PROMPT.md`. A re-export would fall back to the narrower rubric. Copying the
   rule across is a non-additive edit to a frozen file, so it was left for the owner.

## The class-level set

The record is in `experiments/gold/CLASS.md`. In short:
- **Questions.** 99 class pairs, chosen by gap-map band only to stratify. A labeller saw each class's label and
  description (never its synonyms) and wrote either the exact label (50 items) or a paraphrase (49 items),
  plus its own search terms.
- **Candidates.** A taxonomy-free lexical pool over the labeller's terms, plus edges the taxonomy nominates,
  plus edges a recall audit found, shuffled. The labeller never sees where an edge came from.
- **Labels.** Round 2 follows the round-2 gold rubric plus two rules decided on Sat Nov 14: strict class
  membership, and variant-vs-variant contrasts don't vote. Round 1 (0.775 audit) is archived in
  `experiments/gold/class_round1/`.
- **What nomination bought.** 25 items rely on nominated or recall edges. Restricted to the lexical pool
  alone, 15 of 99 labels would change, 9 of them in status. An agent-term pool alone is not enough for class
  questions.
- **Recall audit.** Agents searched `causal_graph.json` directly for all 39 round-1 empties and found edges for
  7. Those edges are now candidates. Roughly 1 in 10 class empties was a false empty before this audit.
- **Blind audit (round 2).** 40 items, seed 47: 33 agree (**0.825**). All 7 disagreements are class-boundary
  calls (basal area vs stem diameter, a combined treatment vs prescribed fire, and the like); the arithmetic
  matched every time. The corrections win at merge.
- **Empty share is 43%.** Strict membership turned 15 of the 57 taxonomy-evidenced pairs into `no_evidence`,
  and gold found evidence for 6 of the 30 taxonomy-empty pairs. The engine reads classes more loosely than
  gold, which is a lead for the taxonomy and linker owners. Accepted on Sat Nov 14; read results split by
  `empty` / `answerable`.

## Eval (default pipeline, 0 LLM calls)

| Set | n | Accuracy | ECE | no_evidence P / R | Retrieval recall | Oracle direction / certainty |
|---|---|---|---|---|---|---|
| Node dev, before (178 items) | 142 | 0.472 | 0.128 | 0.47 / 0.97 | 0.07 | 0.76 / 0.54 |
| Node dev, after (236 items) | 184 | 0.397 | 0.203 | 0.37 / 0.97 | 0.10 | 0.78 / 0.56 |
| **Class dev** | 83 | **0.470** | 0.130 | 0.56 / 0.66 | 0.37 | **0.94** / 0.60 |
| `mise run eval` (both files, dev) | 267 | 0.420 | 0.181 | 0.41 / 0.86 | 0.18 | 0.82 / 0.57 |
| Node holdout (once) | 52 | 0.346 | 0.254 | | | 0.67 / 0.42 |
| Class holdout (once, round 2) | 16 | 0.438 | 0.163 | | | 0.88 / 0.50 |

- Calls per question are 0 in every row.
- Node accuracy fell because the set lost easy empties. On node dev the engine is right on 97% of empties
  and 11% of answered items. The oracle numbers did not move, so the engine did not regress.
- On the class set, direction under oracle edges is 0.94 but certainty is 0.60. On end-to-end answerable
  items the engine is right 33% of the time, so retrieval and linking (retrieval recall 0.37) and certainty
  are the next engine targets.
- `mise run eval` now pools both files. Read each file separately when deciding.

## Reproduce

```sh
export PYTHONPATH=src
# node-level questions and gold (chunks 0001-0005 and gold 0001-0008 are unchanged from #35/#37)
python experiments/devsets/extend_questions.py        # writes questions in/0006 (labelled: out/0006)
python -m camoreasoning annotate merge questions
python -m camoreasoning -s devset_builder=annotated devset --build-only
python -m camoreasoning annotate export gold --chunk 20
rm experiments/annotate/gold/human.jsonl
python experiments/gold/fold_audit.py --reviewer llm:auditor
python -m camoreasoning annotate merge gold
python -m camoreasoning annotate review-import gold --file experiments/annotate/gold/review.csv
python -m camoreasoning annotate review-import gold --file experiments/gold/d3/review_d3.csv
python -m camoreasoning annotate review-import gold --file experiments/gold/audit_new/review.csv
python -m camoreasoning annotate merge gold
python -m camoreasoning -s gold_labeler=annotated devset --gold-only
# class-level set: see experiments/gold/CLASS.md
python experiments/devsets/class_set.py measure       # rubric arithmetic + pool-only comparison
```
