# Node label audit (ROADMAP item 4)

Reproduce the sample with `PYTHONPATH=src python experiments/verify_node_labels.py --seed <seed>`.
Each round audited a fresh random sample of 100 labels, stratified by source (lexical vs LLM). A label
counts as correct only if both the class and the polarity are right. Every round was reviewed by Claude,
not by a human. Fixes were made between rounds, so each later round uses a new seed to avoid grading
the fixes on the sample that motivated them.

| Round | Seed | Change before the round | Edges with both ends labelled | Precision |
|---|---|---|---|---|
| 1 | 2026 | first LLM pass | 93.6% | 79/100 |
| 2 | 7331 | precedence rules; the LLM may not assign generic classes | 80.6% | 84/100 |
| 3 | 9001 | exclosure polarity fix; LLM nativity rule; extra synonyms | 77.2% | 86/100 |

Targets: at least 90% precision and at least 80% edge coverage. Neither is met with the other.

Polarity on removed, absent, decreased and terminated nodes is 1231/1231 correct in round 3. This
check uses the same rule as the labeller, including the survival/mortality and water table depth
inversions, so the audit sample is the real test of polarity.

## Errors left in round 3 (14)

- **Tissue concentrations read as soil or water** (#28, #66, #69, #88). Potassium in corn tissue,
  starch and forest floor phosphorus concentration.
- **Animal life stages read as plant classes** (#32, #51). Oviposition-to-emergence time and salmonid
  biomass.
- **Compound nodes** (#54). "Increased growth, decreased survival and increased browsing" gets the
  node's single qualifier, so survival comes out +1.
- **Second labels that are near-misses** (#7, #12). "Seedling survival rate" also matched the animal
  survival class.
- **Off-topic nodes** (#13, #14, #48, #70). Meta-statements and trait lists picked up a class.
- **LLM nativity guesses** (#85). "Wetland species" labelled native.

## Options

1. Accept about 86% precision and 77% coverage, and let the linker and the retriever's edge checks
   absorb the noise.
2. Spend another rebuild on tissue concentrations and animal life stages. This might gain 4 to 6
   points of precision.
3. Have a human check the 100 labels. The roadmap asks for a hand check, and this audit is not one.
