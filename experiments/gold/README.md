# Gold labels (ROADMAP item 10)

The gold labels for the 178 dev questions in `experiments/devsets/generated.yaml` come from the
`annotate` `gold` task. A labeller reads the candidate edges' `original_sentence` text and applies the
rubric in `experiments/annotate/gold/PROMPT.md` (decisions D2 to D4). It never sees `taxonomy/`, node
labels or pipeline code. A fresh session then audits 40 items, stratified by trap tag. The procedure is
in `AUDIT.md`.

## Round 1: Qwen labels, Opus audits (rejected)

- **Labeller:** the BRINE endpoint model, via `annotate run gold`, in 60 chunks of 3 items. It used the
  original rubric (`PROMPTS["gold"]` in `src/camoreasoning/annotate.py`).
- **Coverage:** 169 of 178 items labelled. Two chunks were cut off at the reply limit and one returned
  nothing.
- **Agreement:** 19 of 40 (0.475), against a target of at least 0.85.
- **Why the labels disagreed:**
  - Certainty was the largest cause: 7 of the 11 misses in part 2 differed only in certainty. Qwen wrote
    `low` almost every time and skipped the one-level drop for mixed or associational evidence.
  - Unsigned relevant edges were labelled `no_evidence`.
  - Edges that report variance explained were given a sign.
  - The rubric itself left gaps: how a study votes when its own edges disagree, the median of an even
    number of grades, and unsigned or non-directional edges.
- **Files:** `round1_qwen/` holds the labels (`qwen_merged.jsonl`), the audited `review.csv`, the
  corrections that `review-import` produced (`human.jsonl`), and each auditor's blind labels and
  verdicts (`audit/`).

## Round 2: Opus labels, fresh Opus audit

- **Rubric:** `PROMPT.md` now spells out D2, D3 and D4 for the gaps above.
  - A study votes with the majority of its signed or null edges. A tie makes the study internally mixed.
  - With an even number of grades, the median is the lower of the two middle grades.
  - Moderates, mediates, precedes, regulates and unchanged-cause edges do not vote.
  - Certainty is computed, never defaulted.
  - These rules come from the locked decisions in ROADMAP.md, not from engine code.
- **Labeller:** `labeler` agents, one per chunk of 20 (`annotate export gold --chunk 20`).
  - Chunks 0002 to 0004 and 0006 to 0009 (138 items) were labelled by Opus.
  - Chunks 0001 and 0005 (40 items) were labelled by Sonnet. The Opus runs on those two chunks were
    stopped by the API's safeguards partway through, and Sonnet relabelled them from scratch.
  - All 178 items are labelled, and `annotate check` is clean.
  - The labels split into 99 `answered` and 79 `no_evidence`. 55 of the 60 random-pair items are
    `no_evidence`.
- **Auditor:** a fresh Opus session on a new sample of 40, drawn with a different seed.
- **Caveat:** the auditor is the same model as the labeller, not a stronger one. This was the
  project's choice after round 1.
