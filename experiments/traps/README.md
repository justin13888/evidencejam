# Trap suite (ROADMAP item 7)

Each trap from `experiments/results/trap_inventory.json` maps to the stage and rule that handle it, and
to a test that runs the engine end to end on a real edge. In the table, `sentence` is
`strategies/interpreter/sentence.py`, `studies` is `aggregator/studies.py`, `rubric` is
`grader/rubric.py`, `precise` is `citer/precise.py` and `searched` is `renderer/searched.py`.

The engine chain is retriever `baseline` → `sentence` → `studies` → `rubric` → `precise` → `searched`.
The linker is bypassed: questions are node-level frames, so these tests isolate the engine from
linking (#5) and labels (#4).

```sh
pytest tests/strategies/test_traps.py tests/strategies/test_direction.py -q
```

| Trap (`trap:<key>` tag) | Stage · rule | Engine behaviour | Test |
|---|---|---|---|
| `reversed_edges` | retriever, `searched` | no_evidence; reverse edge ids named in `searched_for` | `test_reversed_edges` |
| `null_is_not_decrease` | `sentence` rule 1 | null → `no_effect` vote, never decrease. Also when the subject is annotated `unchanged` (130 nulls) | `test_null_is_not_decrease`, `test_null_with_unchanged_subject_is_still_a_null` |
| `associational_is_not_causal` | `sentence` rule 4, `rubric` | votes, tagged `associational`; certainty one level lower (D4) | `test_associational_is_not_causal` |
| ″ (answer wording) | renderer, item 15 | "is associated with", never "causes" (D1) | `test_associational_answer_text_never_says_causes`; `experiments/renderer/consistency_check.py` (d1) |
| `negative_subject_qualifiers` | node polarity × `sentence` rule 7 | decreased/removed subject flips the sign; asking about the removal flips it back | `test_negative_subject_qualifier`, `test_asking_about_the_removal_flips_back` |
| `unchanged_is_not_null` | `sentence` rules 2, 3b, 5, 6 | `unchanged` outcome → `no_effect`; `unchanged` outcome on a significant test → no vote (`unsigned_difference`); `prevents … unchanged` → no vote; categorical `unchanged` cause → no vote | `test_unchanged_outcome_is_a_null`, `test_significant_unchanged_outcome_is_not_a_null`, `test_prevented_change_is_not_a_null` |
| `negative_predicates_double_negation` | `sentence` rule 5 | `prevents`/`disrupts` + decreased/absent object read as one negation (29/30 sign-settled sentences) | `test_double_negation`; all 39 edges in `test_direction.py` |
| `twin_edges_one_sentence` | `studies`, `precise` | one vote per study; disagreeing twins → mixed study; every twin cited | `test_twin_edges_are_one_study`, `test_twins_that_disagree_make_a_mixed_study` |
| `one_study_many_edges` | `studies` | majority within study, then 2/3 across studies (D2) | `test_aggregator_d2` in `test_direction.py` |
| `moderators_mediators` | `sentence` rule 3, `searched` | no vote; no_evidence says "without a direction" | `test_moderators_and_mediators_do_not_vote` |
| `comparator_reference` | `studies` notes | flagged `reference_comparator`; direction unchanged | `test_reference_comparator_is_flagged` |
| `near_miss_classes` | taxonomy (#3/#4) | native vs invasive, survival vs growth, cover vs richness are distinct classes with < 20% node overlap | `test_near_miss_classes_stay_separate` |
| `time_as_cause` | taxonomy (#3) | `time_since_disturbance` shares no nodes with intervention classes | `test_time_is_not_an_intervention` |
| `intervention_name_vs_fields`, `default_positive_subject` | node labeller (#4) | polarity comes from fields, not the name | covered by item 4's label audit |

## Per-tag dev accuracy

Item 7's "done when" also needs `eval` to report accuracy per tag, at or above the overall accuracy.
`mise run eval` reports it under `overall.by_tag`. Each tag, and the overall figure, also carries
`by_gold_status`: accuracy on its gold-answered and its gold no_evidence items separately.

**The bar (#70).** Trap tags come from the seed edge, so trap items are almost all gold-answered, while the
96 gold no_evidence items lift the unsplit overall (0.844 on no_evidence against 0.491 on answered). So
each trap is compared within gold status: its accuracy on gold-answered items must be at or above accuracy
on all gold-answered items. `reversed_edges` has no gold-answered items, so it is compared on gold
no_evidence instead.

Three tests in `test_traps.py` check it for the eight traps item 7 names:

- `test_every_trap_has_three_dev_items` passes. Every trap has at least 5 dev items.
- `test_trap_accuracy_is_at_least_overall` asserts the bar, one case per trap. Six pass.
  `associational_is_not_causal` and `negative_subject_qualifiers` fall short and are **strict xfail
  until #76**.
- `test_engine_reads_every_trap_at_least_as_well_as_overall` passes. The aggregator is fed each item's gold
  edge effects (`evaluate.oracle`) on class-level dev gold. Per trap, its direction accuracy is at or above
  the overall figure.

Measured on the dev split at 0 calls (n = 267, master after #69). Overall accuracy is 0.618: 0.491 on
gold-answered items (n = 171) and 0.844 on gold no_evidence items (n = 96). The overall oracle direction
on class dev is 1.00 (n = 48).

| Trap (`trap:<key>`) | Dev n | End to end | Gold-answered (n) | Bar | Oracle direction, class dev |
|---|---|---|---|---|---|
| `reversed_edges` | 10 | 1.000 | none; no_evidence **1.000** (10) | 0.844 | no class items |
| `twin_edges_one_sentence` | 68 | 0.603 | **0.571** (63) | 0.491 | 1.00 (n = 26) |
| `null_is_not_decrease` | 57 | 0.579 | **0.558** (52) | 0.491 | 1.00 (n = 27) |
| `unchanged_is_not_null` | 18 | 0.500 | **0.500** (16) | 0.491 | 1.00 (n = 2) |
| `moderators_mediators` | 6 | 0.667 | **0.500** (4) | 0.491 | no class items |
| `near_miss_classes` | 5 | 0.600 | **0.500** (4) | 0.491 | 1.00 (n = 4) |
| `negative_subject_qualifiers` | 22 | 0.500 | 0.476 (21) | 0.491 | 1.00 (n = 6) |
| `associational_is_not_causal` | 85 | 0.482 | 0.469 (81) | 0.491 | 1.00 (n = 27) |

The engine reads every trap right when it is given the gold edges. The two shortfalls come from upstream
of the engine, and #76 tracks them:

- **Retrieval.** The common misses are `no_effect → mixed` and `mixed → increase`: other studies come in
  through whole classes, or gold studies are missed (item 5). `widen` and `focus` (#66) recover part of
  this. The linker's "removal/cessation of" flip is fixed (#68, `test_asking_about_an_ending_flips_the_class`).

On node-level `gold_annotated`, the oracle misses 12 items. All 12 are gold `unclear` with only unsigned
gold edges. The oracle counts a vote only when it has an effect, so it turns these into no_evidence. In the
pipeline, the interpreter includes unsigned votes and `studies` returns `unclear` for them. These 12 misses
come from the harness and are not counted as engine errors. `comparator_reference` (0.86 oracle, class dev)
is not one of the eight. See its known limit below.

## Known limits

- **Reference comparators.** These are only flagged. "Restored lower than reference" is still read as the
  treatment lowering Y. Wording that says "compared with undisturbed sites" belongs to the renderer (#15).
- **Double negation.** It has one known miss: cone containers, `disrupts [decreased] survival`, where
  the sentence says survival was higher. `DOUBLE_NEGATION = "schema"` keeps the other reading available
  for the gold comparison.
- **Ties inside a single study.** A study whose twins disagree, with nothing else, gives `mixed`. Baseline
  gives `unclear` there. Gold decides.
