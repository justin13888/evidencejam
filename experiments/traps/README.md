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

## What gold needs for per-tag accuracy

Item 7's "done when" also needs `eval` to report accuracy per tag, at or above the overall accuracy. That
needs at least 3 dev items per trap in `experiments/devsets/`, tagged `trap:<key>` with the keys above. The 5
example edges per trap in `trap_inventory.json` are seeds for those items (#9).

## Known limits

- **Reference comparators.** These are only flagged. "Restored lower than reference" is still read as the
  treatment lowering Y. Wording that says "compared with undisturbed sites" belongs to the renderer (#15).
- **Double negation.** It has one known miss: cone containers, `disrupts [decreased] survival`, where
  the sentence says survival was higher. `DOUBLE_NEGATION = "schema"` keeps the other reading available
  for the gold comparison.
- **Ties inside a single study.** A study whose twins disagree, with nothing else, gives `mixed`. Baseline
  gives `unclear` there. Gold decides.
