# Roadmap

**Submission:** the last commit before **Sun Nov 15, 18:00 EST**. Freeze at 16:00.

**Ranking:** the winner is the highest total. 60 points are scored by script on a hidden question set and 40 by judges.

### Points key

Every item lists the buckets it moves.

| Key | Points | What it covers |
|---|---|---|
| **D17** | 17 | Direction, null vs effect, certainty, not fooled by traps |
| **C14** | 14 | Confidence calibration, plus `no_evidence` with `searched_for` (about 1/3 of hidden questions) |
| **P9** | 9 | Answers parse; cited edges exist and bear on the question |
| **E12** | 12 | Energy per question, ranked against other teams. Counts only if at least half our answers are correct, so never trade accuracy for it |
| **R8** | 8 | Runs from a clean checkout. If more than 5% of entries don't parse, all scripted points are halved |
| **J40** | 40 | Judges: method, faithfulness, honest limits, user value, craft and reuse, W3C accessibility |

### Format

- **★ n/5:** how hard to try.
- **Streams:** A = taxonomy and linking, B = reasoning engine, C = eval and calibration, D = energy, product and release.
- **`stage`:** the component in `components.py` that the item lives in. Work is a new strategy for that stage.

### Dependency tree

`A --> B` means B needs A's output first. Numbers are the items below. Item 0 is done and feeds everything, so it is omitted.

```mermaid
flowchart LR
  1[1 Profile graph] --> 3[3 Taxonomy]
  1 --> 7[7 Trap suite]
  2[2 Profile LLM] --> 5
  2 --> 14[14 Cut energy]
  3 --> 4[4 Node labels]
  3 --> 5[5 Linker]
  3 --> 9[9 Gold dev set]
  3 --> 17[17 Gap map]
  4 --> 6[6 Direction]
  4 --> 13[13 Citer]
  4 --> 17
  5 --> 6
  5 --> 14
  5 --> 18[18 Ask CLI]
  6 --> 7
  6 --> 8[8 no_evidence]
  6 --> 11[11 Certainty]
  9 --> 10[10 Gold labeller]
  10 --> 6
  10 --> 7
  10 --> 8
  10 --> 11
  10 --> 12[12 Calibration]
  6 --> 12
  8 --> 12
  11 --> 12
  6 --> 15[15 Answer text]
  8 --> 15
  11 --> 15
  13 --> 16[16 Evidence pages]
  15 --> 16
  12 --> 16
  3 --> 17
  16 --> 19[19 Accessibility]
  17 --> 19
  20[20 Limits page] --> 19
  10 --> 20
  12 --> 20
  7 --> 20
  12 --> 21[21 README]
  14 --> 21
  14 --> 22[22 Clean-checkout run]
  15 --> 22
  16 --> 22
  18 --> 22
  22 --> 23[23 Freeze and submit]
  19 --> 23
  21 --> 23
  5 -.-> 24[24 Embeddings]
  6 -.-> 26[26 Multi-hop]
```

**Critical path:** 1 → 3 → 4 → 5 → 6 → 8 → 12 → 16 → 22 → 23. Anything slipping on it moves the submission.

**Layers (what can run in parallel):**

| Layer | Items | Needs |
|---|---|---|
| L0 | 1, 2 | nothing |
| L1 | 3 | 1 |
| L2 | 4, 5, 9 | 3 (5 also uses 2) |
| L3 | 10, 6, 17, 18 | 9 for 10; 4 and 5 for 6; 3 and 4 for 17; 5 for 18 |
| L4 | 7, 8, 11, 13, 14 | 6 (13 needs 4; 14 needs 5 and 2) |
| L5 | 12, 15 | 6, 8, 11 and 10 |
| L6 | 16, 20, 21 | 12, 13, 15 for 16; 7, 10, 12 for 20; 12, 14 for 21 |
| L7 | 19, 22 | pages built (16, 17, 20); 22 needs 14, 15, 16, 18 |
| L8 | 23 | 19, 21, 22 |

**Notes:**
- 10 (the independent gold labeller) is also an input to tuning 6, 7, 8, 11 and 12. Items 4, 5 and 9 can start as soon as 3 lands, and 9 can run in parallel with 4.
- 14 and 22 must re-run after any change that alters accuracy, so treat them as gates rather than one-off steps.

## Phase 0 — Foundation (done)

- [x] **0. Frozen contracts, tooling and baselines.** ★ 5/5 · all
  - **Why:** four people and many agents work in parallel without breaking each other.
  - **Done when:** `mise run check` and `mise run robust` are green, and `./run.sh` works from a clean clone with 0 LLM calls.
  - **Points:** R8, P9 floor.

## Phase 1 — Understand (Fri night)

- [x] **1. Profile the CAMO graph.** ★ 4/5 · A · `experiments/`
  - **Why:** the taxonomy, sign rules and traps must fit this graph, not CAMO in general. Every edge is graded moderate, low or very_low, never high. There are no assessment edges. 5,067 of 6,814 nodes appear in only one edge. 661 of 1,906 signed edges flip sign under naive reading. There are 1,093 null findings and 203 `unchanged` nodes.
  - **Done when:** `mise run profile` output is reviewed. Cause and outcome vocabulary is dumped. A trap inventory with counts goes in `experiments/`, including twin edges from one sentence and `associated_with` with qualifiers.
  - **Points:** feeds D17 and C14.
  - **Done:** the review is in `experiments/profile/README.md`. The vocabulary is in `vocab_*.tsv`, and the trap inventory, with 5 examples per trap, is in `experiments/results/trap_inventory.json`. Every "Why" number checked out.
    - **Fragmentation:** 4,801 of 4,820 raw cause→outcome pairs rest on one document, so item 3 must merge hard.
    - **Open for item 6:** all 39 `prevents`/`disrupts` edges double-negate ("prevents decreased Y"), so the schema sign product reads the opposite of the sentence.
    - **For items 6 and 8:** the 121 `unchanged` objects are untagged nulls.
- [x] **2. Profile the instrumentation.** ★ 4/5 · D · `llm.py` usage
  - **Why:** E12 is estimated from tokens on the endpoint. We need to know whether thinking-off really works, whether usage is reported, and how latency behaves.
  - **Done when:** a smoke call through `ctx.llm` records prompt and completion tokens in `footprint.json`. Completion tokens are small, so no hidden reasoning. The batch chunk size is chosen, and the baseline tokens per question are written down here.
  - **Points:** E12, R8.
  - **Done:** the probe is in `experiments/results/endpoint_probe.json` and the chunk sweep in `experiments/results/llm_chunk_size.json` (`experiments/llm_profile/chunk_size.py`).
    - **Usage and thinking:** the endpoint reports real prompt and completion tokens. Thinking-off holds: an "OK" reply costs 2 completion tokens and has no `<think>`. JSON-schema `response_format` works.
    - **Cost is the prompt:** 0.2 s for a short prompt, about 5.6 s for 2.6k prompt tokens. There is no prefix cache, so a repeated prompt costs the same every time.
    - **Chunk size:** put every fallback question in one call. Over 50 synthetic template questions, tokens per question fall from 403 (1 per call) to 49 (50 per call), and accuracy does not drop. `tokens_per_item=32` is enough, since 17–24 were used.
    - **Baseline:** 0 tokens per question for the default pipeline, since the lexical linker makes no calls. About 49 tokens per question if every question used the batched LLM fallback.
    - **For items 5, 14 and 18:** latency varies on the server side, from 4 s to 100 s for similar calls, so `ask` needs a short timeout with a lexical fallback. With only the class-id list, the LLM links both sides right 52–60% of the time, so lexical matching must stay primary.

## Phase 2 — Core engine (Sat)

- [ ] **3. Build the taxonomy (class inventory).** ★ 5/5 · A · `taxonomy_builder`
  - **Why:** hidden questions name broad classes, like "mulch & surface cover" or "invasive / non-native species abundance", while nodes are specific to one paper. Every answer goes through these classes.
  - **Done when:**
    - Every concept in the CHALLENGE examples and the practice questions maps to a class.
    - Near-misses stay separate: native vs non-native, survival vs growth, cover vs richness.
    - Roughly 30–80 cause classes (interventions and conditions) and 40–100 outcome classes, each with synonyms.
  - **Points:** D17, C14 and P9. Almost all 40 scripted accuracy points rest on it. Also J40: it gives the gap map its axes.
- [ ] **4. Label nodes with classes and polarity (offline LLM).** ★ 5/5 · A · `node_labeler`
  - **Why:** retrieval and sign reading depend on knowing what each node is and which way it points ("removal of buckthorn" = invasive abundance −1).
  - **Done when:**
    - At least 90% precision on 100 hand-checked labels.
    - Polarity is right on removed, absent and decreased nodes.
    - At least 80% of edges have both endpoints labelled.
    - The artifact is committed and the build is reproducible.
  - **Points:** D17, C14, P9.
- [ ] **5. Link questions to classes.** ★ 5/5 · A · `linker`
  - **Why:** a wrong class pair is a wrong answer, and judges also phrase their own questions.
  - **Done when:**
    - At least 95% of dev questions get the right classes, including paraphrases.
    - Template questions resolve with 0 calls.
    - Questions with a low match margin go to the LLM, all in one batched call.
  - **Points:** D17, C14, E12.
- [ ] **6. Aggregate direction.** ★ 5/5 · B · `interpreter`, `aggregator`
  - **Why:** direction is the biggest share of D17. It needs schema sign composition, one vote per study, nulls counted as findings, and "mixed" when studies disagree.
  - **Done when:** at least 85% direction accuracy on dev answerable items, and the thresholds are tuned on dev only.
  - **Points:** D17.
- [ ] **7. Build the trap suite.** ★ 5/5 · B · `interpreter`, `aggregator`, `tests`
  - **Why:** the hidden set includes questions "written to catch common misreadings".
  - **Done when:** each trap has at least 3 tagged dev items, and `eval` reports accuracy per tag at or above the overall accuracy. The traps:
    - reversed edges
    - null ≠ decrease
    - associational ≠ causal
    - `removed` or `decreased` subjects
    - `unchanged` ≠ null
    - twin edges from one sentence
    - moderators and mediators
    - near-miss classes
  - **Points:** D17 (explicitly "not fooled by trap questions").
- [ ] **8. Decide no_evidence and write searched_for.** ★ 5/5 · B · `aggregator`, `renderer`
  - **Why:** about 1/3 of hidden questions have no evidence, and a confident wrong "answered" costs both D17 and C14.
  - **Done when:** `no_evidence` precision and recall are both at least 0.9 on dev, and `searched_for` names the classes, attributes and relation searched, plus any reverse edges found.
  - **Points:** C14, D17.
- [ ] **9. Build the gold dev set.** ★ 5/5 · C · `devset_builder`
  - **Why:** the hidden set is scored at judging time and `questions.yaml` has no answers. Without labels we tune on vibes.
  - **Done when:**
    - At least 90 items in the hidden template, about 1/3 empty, trap-tagged, with paraphrased class names.
    - About 20% are held out and never tuned on.
  - **Points:** enables D17, C14, P9 (everything measurable).
- [ ] **10. Keep the gold labeller independent.** ★ 5/5 · C · `gold_labeler`
  - **Why:** gold made by our own sign code makes the eval circular. The gold labeller is an LLM reading `original_sentence` text, plus a human audit.
  - **Done when:**
    - The import guard test passes.
    - At least 40 items are human-audited, with at least 85% LLM–human agreement.
    - Disagreements become trap tests.
  - **Points:** the D17 and C14 numbers become trustworthy.
- [ ] **11. Grade certainty.** ★ 4/5 · B · `grader`
  - **Why:** certainty is part of D17. The graph has no `high` grades, so the grade has to be derived from edge grades, study count, agreement and design (randomized vs observational).
  - **Done when:** the rule is written in the strategy docstring and scores at least 75% certainty accuracy on dev.
  - **Points:** D17.
- [ ] **12. Calibrate confidence.** ★ 4/5 · C · `calibrator`
  - **Why:** 14 points reward confidence that matches how often we're right.
  - **Done when:**
    - The fit uses the `Features` on dev, and holdout ECE is at most 0.05.
    - No confidence goes above 0.95.
    - The parameters are committed under `experiments/`, and a reliability table is in the extras.
  - **Points:** C14.
- [ ] **13. Select cited edges.** ★ 4/5 · B · `citer`
  - **Why:** scripts check that the cited edges "are the edges that bear on the question", and judges open them.
  - **Done when:** precision comes first. On dev, edge precision is at least 0.9 and recall at least 0.7.
  - **Points:** P9, J40.
- [ ] **14. Cut energy without losing accuracy.** ★ 4/5 · D · `linker`, `llm.py` usage
  - **Why:** E12 is ranked against teams. Only runtime tokens count, so push work offline.
  - **Done when:**
    - At least 90% of template questions need 0 calls, and the rest share one batched call.
    - Prompts use class ids, not prose.
    - `tokens_per_question` is tracked in every eval.
    - Accuracy stays the same.
  - **Points:** E12 (gated on at least 50% correct).

## Phase 3 — Product and proof (Sun AM)

- [ ] **15. Write the answer text.** ★ 3/5 · B · `renderer`
  - **Why:** judges check faithfulness. Use one hedge source (the certainty), name null studies, count studies, and never claim causation from association. Follow the organizer's [rendering guide](https://github.com/timalamenciak/causalmosaic/blob/main/docs/camo-rendering-targets.md). It is referenced, not vendored. Where it conflicts with `schema/`, the schema wins.
  - **Done when:** 20 sampled answers are reviewed against their cited edges with zero overclaims.
  - **Points:** J40.
- [ ] **16. Build evidence pages.** ★ 3/5 · D · `extras`
  - **Why:** judges open what `extras` lists.
  - **Done when:** each page shows the answer card (direction, certainty and confidence kept separate), a vote table per study with quotes, DOIs and comparators, the sign trace, and excluded and reversed edges.
  - **Points:** J40.
- [ ] **17. Build the gap map.** ★ 3/5 · D · `extras`
  - **Why:** it turns "no evidence" into a visible, useful product and shows where the graph is dense or empty.
  - **Done when:** the cause × outcome grid shows study counts, empty cells are labelled "gap", and each cell links to example questions.
  - **Points:** J40, and shows C14 behaviour.
- [ ] **18. Handle judges' own questions with the ask CLI.** ★ 4/5 · A · `parser`, `linker`
  - **Why:** each judge asks one real question of their own.
  - **Done when:** free-form wording links through the LLM fallback, it never crashes, it answers in under 10 s, and it is tested on 20 off-template questions.
  - **Points:** J40.
- [ ] **19. Audit accessibility.** ★ 3/5 · D · `product/`, `extras`
  - **Why:** W3C criteria are judged.
  - **Done when:** WCAG 2.2 AA is checked by hand and with a checker, covering contrast, headings, table headers, `lang`, keyboard use, no colour-only meaning, and reflow at 320 px.
  - **Points:** J40.
- [ ] **20. Write an honest-limits page.** ★ 3/5 · C · `extras`
  - **Why:** judges ask "Does it show where it fails, with examples?"
  - **Done when:** the page shows real holdout failures by trap tag, the reliability table, and what we deliberately don't do (multi-hop, effect sizes).
  - **Points:** J40.
- [ ] **21. Write the README method and extend guide.** ★ 3/5 · D · docs
  - **Why:** judges score method and fit, and craft and reuse.
  - **Done when:** the README explains the method in 4 steps with the headline eval numbers, and another team could add a strategy in 10 minutes.
  - **Points:** J40.

## Phase 4 — Release (Sun PM)

- [ ] **22. Rehearse a clean-checkout run.** ★ 5/5 · D · `scripts/`
  - **Why:** it protects R8 and guards against halving all 60 scripted points.
  - **Done when:**
    - `mise run judge-sim` passes: ARM64, Python 3.10, offline with a dead LLM.
    - A real endpoint run passes from a fresh clone.
    - 500 questions finish in under 60 s.
  - **Points:** R8, P9, all 60.
- [ ] **23. Freeze and submit.** ★ 5/5 · all
  - **Why:** only the last commit before 18:00 counts.
  - **Done when:** feature freeze is 16:00. Defaults are set to the best eval, `mise run ci` is green, the commit is tagged `submission`, and no `.env` or keys are in history.
  - **Points:** everything.

## Stretch (only if all ★5 items are done)

- [ ] **24. Local static embeddings for linking.** ★ 2/5 · A · `linker`
  - Only if lexical + LLM linking misses on dev. The weights would have to be committed and numpy added. Points: D17.
- [ ] **25. HTTP/MCP server over the pipeline.** ★ 1/5 · D
  - Points: J40, craft and reuse, marginal.
- [ ] **26. Multi-hop chains.** ★ 1/5 · B
  - Only as labelled extras. Never used in scored answers, since it risks false answers on the 1/3 that are `no_evidence`.
