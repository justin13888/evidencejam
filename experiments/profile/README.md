# Graph profile review (ROADMAP item 1)

What this graph looks like and how it can fool a reader. Everything below comes from the committed
outputs. Re-run the scripts after any change to the graph or the sign helpers.

```sh
mise run profile                      # -> experiments/results/graph_profile.json (field coverage, vocabularies)
python experiments/profile/vocab.py   # -> vocab_causes.tsv, vocab_outcomes.tsv, vocab_summary.json
python experiments/profile/traps.py   # -> trap_inventory.json (counts + 5 checkable examples per trap)
```

Both scripts make no LLM calls and give the same output every run. They import signs only from
`camoreasoning.signs`, and they assert their totals against `profile_graph` (edge totals, 1,093 nulls,
661 sign flips), so they fail loudly if the graph or sign code drifts.

## Headline facts (verified)

| Claim in ROADMAP item 1 | Measured | OK |
|---|---|---|
| Grades are only moderate / low / very_low | 2,885 / 2,143 / 526. No `high`, no `not_assessed` | ✓ |
| No assessment edges | top-level keys are `graph_id, provenance, schema_version, nodes, edges, source_documents`. No `evidence_base_assessments` | ✓ |
| 5,067 of 6,814 nodes appear in only one edge | 5,067. Every node is used by at least one edge | ✓ |
| 661 of 1,906 signed edges flip sign under naive reading | 661 (66 from a negative subject, 595 from a negative object qualifier) | ✓ |
| 1,093 null findings | 1,093. `negated` ⇔ `no_relationship` exactly, with no edge having only one of the two | ✓ |
| 203 `unchanged` nodes | 203 | ✓ |

Other facts that matter:

- **Scale:** 5,554 edges, 293 documents (292 with edges). Edges per document: median 16, max 91.
- **Node reuse is almost nil.** Only 199 nodes are shared across documents. Grouped by readable concept
  (entity label + attribute, CURIEs resolved via `embedding_text`), there are 1,933 cause concepts and
  3,084 outcome concepts. Only 153 cause and 208 outcome concepts appear in 2 or more documents, and
  **4,801 of 4,820 raw cause→outcome concept pairs rest on a single document.** Without class merging
  nearly every answer is one study.
- **Predicates:** `causes` 2,900, `associated_with` 2,233, `correlated_with` 279, `contributes_to` 47,
  `prevents` 30, `enables` 28, `moderates` 22, `disrupts` 9, `mediates` 4, `regulates` 2, `precedes` 0.
  Only 1,906 edges (34%) carry a predicate sign.
- **Nulls:** 1,077 of the 1,093 nulls are `causes` with `negated: true`. 1,076 have no object qualifier.
- **Design drives grade.** `moderate` is 75% randomized_experiment (2,176/2,885). `low` is mostly
  observational_cross_sectional (1,365). `very_low` comes from modeling, case studies and cross-sectional work.
  Item 11 can take design × study count × agreement as its inputs.
- **Outcome attributes are concentrated:** cover 572, abundance 289, concentration 272, density 218,
  species richness 138 (+ richness 96), presence 134, survival 131, composition 121, biomass 120.
  This is a good backbone for outcome classes.
- **Top cause concepts by documents:** time (27 docs), fertilization (10), restoration (9), seeding (8),
  herbicide application (6), scarification (5), cutting (5), burning (5). 718 intervention concepts and
  1,215 condition concepts (variables, processes or taxa as subject).
- **Degenerate records:** 14 self-loops, 1 node without `entity_type` (`camo:node_3d7d179f15ce`), 1 comparator
  with null type (`camo:edge_cbaa0d8cde38`), 1 edge without `strength` (`camo:edge_8ace2637a313`). No
  dangling ids. Every `source_document` resolves.
- **Ecosystems:** boreal/temperate forests 1,237, peat bogs 758, subhumid grasslands 603, deciduous
  forests 475, plantations 280, then a long tail. 237 edges have no ecosystem.

## Trap inventory

Counts are edges unless noted. "Example" is the first example in `trap_inventory.json`. Each trap there
has 5 examples with the quoted sentence, enough to seed at least 3 dev items per trap for items 7 and 9.

| Trap | Count | % edges | Stage that must handle it | Example |
|---|---:|---:|---|---|
| Associational ≠ causal (non-null `associated_with`/`correlated_with`) | 2,496 | 44.9 | interpreter, grader, renderer | `camo:edge_9ab77deefcdf` |
| … of which both endpoints carry signed qualifiers (direction from qualifiers only) | 1,646 | 29.6 | interpreter | |
| Twin edges from one sentence (edges in sentences with 2 or more edges) | 1,728 | 31.1 | aggregator, citer, grader | `camo:edge_82cc8c02077b` |
| … sentences with one null and one non-null twin | 80 sentences | | aggregator | |
| Default +1 subject (`occurred`/none/`ongoing` with a signed predicate) | 1,438 | 25.9 | interpreter | `camo:edge_f6d8b9c0883c` |
| One study, many edges on one concept pair | 1,227 | 22.1 | aggregator (one vote per document) | `camo:edge_e5968ebcad3b` |
| … document-pairs that disagree internally | 124 pairs | | aggregator, grader | |
| Null ≠ decrease | 1,093 | 19.7 | interpreter, aggregator | `camo:edge_5e5b83097577` |
| Reference comparator only (`reference_undisturbed`) | 622 | 11.2 | interpreter, renderer | `camo:edge_e764a1d31956` |
| Time / age / duration as cause | 392 | 7.1 | taxonomy_builder, linker | `camo:edge_3a223681d917` |
| Negative-qualifier subject (decreased 181, removed 43, terminated 27, absent 25, interrupted 2) | 278 | 5.0 | node_labeler, interpreter | `camo:edge_f2c1bfb5b95f` |
| `unchanged` endpoint (121 objects, **all** non-negated) | 268 | 4.8 | interpreter, aggregator | `camo:edge_07b5d3056850` |
| Intervention name vs fields (intervention subject with a negative qualifier) | 98 | 1.8 | node_labeler, linker | `camo:edge_b1b296daafda` |
| Double negation: `prevents`/`disrupts` + negative object qualifier | 39 (all 39) | 0.7 | interpreter, gold_labeler | `camo:edge_088dcd02e0a5` |
| Near-miss classes (nodes matching both sides of a pair) | 38 nodes | | taxonomy_builder, linker | `camo:edge_862d39c58d4d` |
| Moderators / mediators (`moderates` 22, `mediates` 4, `regulates` 2) | 28 | 0.5 | interpreter (no vote) | `camo:edge_c06d529dc25e` |
| Reversed edges (raw entity pairs found in both directions) | 20 (9 pairs) | 0.4 | linker, retriever | `camo:edge_fb3489f963a3` |

### What the spot-checks showed

At least 3 examples per trap were read against `original_sentence`.

- **Double negation is a graph error, and the schema rule gets it wrong.** All 39 `prevents`/`disrupts`
  edges have an object qualifier that restates the drop: "rewetting *prevents* *decreased* Kalmia cover"
  for "Kalmia cover was significantly lower in rewetted trenches". The schema product (+1)(−1)(−1) = +1
  reads "increase", the opposite of the sentence. The same holds for caging→breakage, soil→browning,
  cover crop→weeds, Sanguinaria→Alliaria, and others. This is **an open decision for item 6**: either
  follow the schema rule, or treat a negative predicate with a negative object as a single negative. Gold
  (item 10) reads sentences, so it will expose which way the hidden set leans. Keep these edges out of
  threshold tuning until then.
- **Names lie, fields don't.** `Kalmia control with herbicide` has `entity_term` = Kalmia (wd:Q3192236),
  `measured_attribute` = cover and qualifier `decreased`. So "decreased Kalmia cover causes increased
  conifer height" is correctly −1 for *Kalmia → height*. The herbicide only lives in the name. "Release
  from moose browsing" [removed] works the same way. Item 4 must label from `entity_term` +
  `measured_attribute` + qualifier, and recover the intervention from the name as a second label.
- **`unchanged` objects are null findings that are not tagged as null.** None of the 121 are negated,
  70 are `associated_with`, and they read as "X associated with no change in Y". Treat them as
  `no_effect` votes, or at least never as signed votes. The interpreter must decide this explicitly.
- **Twins split one claim per site, year or species.** For example, "Assisted restoration at Coniston"
  increased richness while "…at Daisy Lake" showed no difference, in one sentence. Within one document,
  that is site heterogeneity, not between-study "mixed".
- **Reference comparators** (622) compare restored with undisturbed sites. "Restored lower than reference"
  means not yet recovered, not that the treatment lowers Y.
- **Associational edges are the plurality.** 1,646 have a direction implied only by the qualifiers. Wording
  must stay associational, and the grade is lower.
- **Reversed edges are rare at node level** (9 entity pairs), because nodes are per-paper. The real risk
  is a hidden question written in reverse, where gold is `no_evidence` with the reverse edges named in
  `searched_for`. The other risk is class-level reversal once concepts merge. 182 concepts are used as
  both cause and outcome (442 edges). **Re-count after item 3.**
- **Near-miss:** "Decreased cover of native and nonnative species" and "native forb cover and richness"
  are single nodes that span two classes. Labels need to allow 2 classes per node. 18 documents report
  both native and non-native outcomes, 48 both cover and richness, 35 both survival and growth.
- **Nulls almost never carry an object qualifier** (1,076/1,093 have none). A "does X decrease Y?"
  question on a null edge has gold `no_effect`, not `decrease`.

## Implications for downstream items

- **3 Taxonomy.** Raw concepts are too fragmented for answering: 4,801 of 4,820 pairs rest on one document.
  Classes must merge hard. Build outcome classes from the concentrated attribute vocabulary (cover,
  abundance/density, richness/diversity, survival, growth/height/biomass, concentration, presence)
  crossed with entity groups (native vs non-native plants, conifers, mosses/Sphagnum, fish, inverts,
  soil C/N/pH, water table, GHG fluxes). Give **time/age** its own condition class so it never answers
  an intervention question. Keep near-miss pairs separate. Use `vocab_causes.tsv` / `vocab_outcomes.tsv`
  (sorted by documents) as the coverage checklist.
- **4 Node labels.** Polarity cases by subject qualifier: occurred 1,653 / introduced 823 / present 116
  are +1; removed 51, terminated 27, decreased 22, absent 13 on interventions need the
  intervention-vs-target split above. Allow multi-class nodes.
- **6 Direction.** Use one vote per document; 516 document-pairs have 2 or more edges, and 124 conflict
  internally. Nulls vote `no_effect`. `unchanged` objects are null-like. Structural predicates don't
  vote. Associational votes are allowed but flagged. Decide the double-negation rule explicitly.
- **7 Traps.** Every trap above has 5 example edges with sentences in `trap_inventory.json`. Tag dev items
  with these trap keys so `eval` can report per-tag accuracy.
- **8 no_evidence.** Coverage is very sparse, so `no_evidence` is the default outcome for most class
  pairs. `searched_for` should name reverse-direction edges when they exist.
- **11 Certainty.** Grade tracks design. Most class-level answers will rest on 1–3 documents, so
  `high` should be essentially unreachable.
- **13 Citer.** Dedupe twin edges per sentence, and cite the twin whose concept pair matches the question.

## Files

| File | What |
|---|---|
| `experiments/results/graph_profile.json` | `mise run profile`: coverage, field vocabularies, degree, sign agree/disagree |
| `experiments/results/vocab_causes.tsv` | subject-side concepts: entity_type, edges, documents, null edges, qualifiers, example names and ids |
| `experiments/results/vocab_outcomes.tsv` | the same for the object side |
| `experiments/results/vocab_summary.json` | concept counts, intervention vs condition causes, top entity/attribute/applied_to terms |
| `experiments/results/trap_inventory.json` | the trap counts, breakdowns, 5 examples each, certainty × design, degenerate records |
