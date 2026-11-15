# Gold labels (ROADMAP item 10)

The gold labels for the 178 questions (142 dev, 36 holdout) in `experiments/devsets/generated.yaml`
come from the `annotate` `gold` task. A labeller reads the candidate edges' `original_sentence` text and
applies the rubric in `experiments/annotate/gold/PROMPT.md` (decisions D2 to D4). Its input chunks
(`in/*.jsonl`) hold only the question, the candidate edges and their sentences, with no taxonomy content.
It is told not to open `taxonomy/`, node labels or pipeline code; that is an instruction, since agent file
reads were not logged. A separate auditor session then audits 40 items, stratified by trap tag. The
procedure is in `AUDIT.md`.

## Round 1: labeller A (rejected)

- **Labeller:** `annotate run gold`, with the original rubric (`PROMPTS["gold"]` in
  `src/camoreasoning/annotate.py`).
- **Coverage:** 169 of 178 items labelled. Two chunks were cut off at the reply limit and one returned
  nothing.
- **Agreement:** 19 of 40 (0.475), against a target of at least 0.85.
- **Why the labels disagreed:**
  - Certainty was the largest cause: it differed in 19 of the 21 misses. In 8 of the 11 misses in part 2,
    status and direction matched and certainty did not. The labeller wrote `low` on 55 of its 82
    answered items and skipped the one-level drop for mixed or associational evidence.
  - Unsigned relevant edges were labelled `no_evidence`.
  - Edges that report variance explained were given a sign.
  - The rubric itself left gaps: how a study votes when its own edges disagree, the median of an even
    number of grades, and unsigned or non-directional edges.
- **Files:** `round1/` holds the labels (`merged.jsonl`), the audited `review.csv`, the corrections
  that `review-import` produced (`human.jsonl`), and the auditor's blind labels and verdicts (`audit/`).

## Round 2: labeller B, fresh audit

- **Rubric:** `PROMPT.md` now spells out D2, D3 and D4 for the gaps above. Where the locked text in
  ROADMAP.md is silent, these are our readings of it, not engine code:
  - A study votes with the majority of its signed or null edges. A tie makes the study internally mixed.
  - With an even number of grades, the median is the lower of the two middle grades.
  - Moderates, mediates, precedes, regulates and unchanged-cause edges do not vote.
  - Certainty is computed, never defaulted.
- **Labeller:** `labeler` agents, one per chunk of 20 (`annotate export gold --chunk 20`).
  - The first runs on chunks 0001 and 0005 (40 items) stopped partway, and both chunks were relabelled
    from scratch in new sessions.
  - All 178 items are labelled, and `annotate check` is clean.
  - The labels split into 99 `answered` and 79 `no_evidence`. 55 of the 60 random-pair items are
    `no_evidence`.
- **Auditor:** a new session on a new sample of 40, drawn with a different seed (11 items overlap with
  round 1's sample). It covers all 8 trap tags (4 to 13 items each), 8 items with no trap tag, and
  26 `answered` and 14 `no_evidence` labels.
- **Agreement:** 37 of 40 (0.925). The 3 corrections win at merge and are trap tests in
  `tests/strategies/test_gold_disagreements.py`.
- **Override:** the auditor is not a stronger model than the labeller, which item 10 asks for. This was
  accepted on purpose; see the item 10 note in ROADMAP.md.

## Issue #9 audit (after round 2)

`experiments/devsets/AUDIT.md` has the full audit. Changes to this set:

- **D3 null rule.** A null (`negated: true`) now votes 0 even when its cause is `unchanged`. A blind relabel
  of 27 affected items (`d3/`, `d3_relabel.py`) changed D-Q0022, Q0025, Q0028 and Q0069. Only differences
  that the rule caused were applied; the source is `llm:d3-relabel`.
- **New items.** 58 forward edge seeds were added (Q0181–Q0240, `experiments/devsets/extend_questions.py`).
  Gold chunks 0010–0012 are new, and 0009 gained 2 rows; old rows and inputs are byte-identical. A blind
  audit of 16 new items (`audit_new/`) agreed on 15 (0.94); its correction of D-Q0222 wins.
- **Trap tags** use the `trap_inventory.json` keys (`strategies/devset_builder/_traps.py`).
- The class-level set is recorded in `CLASS.md`.

## Issue #49: re-check of 4 possible false empties

The labeller wrote "candidates incomplete" on 4 `no_evidence` items (D-Q0101, Q0121, Q0122, Q0162; AUDIT.md
finding 5). `recheck_empties/` holds the re-check, run by `recheck_empties/recheck.py`:

- **Search.** A searcher read only `questions.jsonl` and `causal_graph.json`, with no taxonomy, and wrote
  `found.jsonl`: 2 edges for Q0101, none for Q0121, 2 for Q0122 and 10 for Q0162.
- **Relabel.** A fresh labeller read only `PROMPT.md` and `blind.jsonl` (each item's candidates, with the
  found edges it lacked appended last) and wrote `relabel.jsonl`.
- **Flip rule.** An item flips only if the relabel cites edges that give a direction (effect 1, -1 or 0).
  Otherwise it stays `no_evidence`.
- **Result.** Only D-Q0101 flips, to `decrease`, `very_low`, on `camo:edge_3019a2266311` (sculpin density
  is lower at sites with invasive round goby). `recheck.py extend` appended that edge to the item's input
  row as `e24`. The other 3 stay `no_evidence`. The source is `llm:recheck-relabel`.
- **Gold counts.** Dev is now 123 answered and 61 `no_evidence` (was 122 and 62). Holdout is unchanged at
  36 and 16.

## Reproduce

From `audit/`, `d3/`, `audit_new/`, `recheck_empties/` and the labeller outputs, this chain rebuilds
`human.jsonl`, `merged.jsonl` and `experiments/devsets/gold_annotated.yaml` byte for byte (verified Sat
Nov 14, after issue #49):

```sh
export PYTHONPATH=src
rm experiments/annotate/gold/human.jsonl
python experiments/gold/fold_audit.py --reviewer llm:auditor
python -m camoreasoning annotate merge gold
python -m camoreasoning annotate review-import gold --file experiments/annotate/gold/review.csv
python -m camoreasoning annotate review-import gold --file experiments/gold/d3/review_d3.csv
python -m camoreasoning annotate review-import gold --file experiments/gold/audit_new/review.csv
python -m camoreasoning annotate review-import gold --file experiments/gold/recheck_empties/review.csv
python -m camoreasoning annotate merge gold
python -m camoreasoning -s gold_labeler=annotated devset --gold-only
```
