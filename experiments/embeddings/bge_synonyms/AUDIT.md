# Synonym audit: graph wording -> class synonym

You decide, for each graph term in `audit/in_NNNN.jsonl`, whether it (or a shorter specific core of it)
should become a synonym of one class in `taxonomy/curated_classes.yaml`. Read that file first: every
class's id, kind, label, synonyms and description, and its header comment.

## What a synonym does

A synonym is a lower-case phrase matched on word boundaries (a trailing `*` means "any word ending")
against **every node's** name, entity term and measured attribute, **and against the cause and outcome
text of user questions**. A node or question side whose text contains the phrase is placed in that
class. So a synonym is right only if *any* text containing it belongs to the class, not just the
examples shown. One bad generic synonym mislabels hundreds of nodes ("disturbance" had to be removed).

## Input line

`{"id", "term", "nodes", "examples", "types", "llm_labels", "bge_top3"}`: the term, how many graph nodes
use it, up to 3 of their names, their entity types, the class ids an earlier LLM pass gave those nodes,
and the 3 classes a sentence-embedding model (BGE) ranks closest, with cosines. `llm_labels` and
`bge_top3` are hints only and are often wrong. You may pick any class.

## Accept only when all hold

1. The phrase names what the class covers, in ecology usage: the intervention, condition or measured
   outcome the class describes. It is not just related to it.
2. It is specific. Reject bare generic words and phrases that would match unrelated text: `cover`, `site`,
   `time`, `treatment`, `vegetation`, `tree`, `trees`, `interaction`, `distance`, `depth`, `rate`,
   `density`, `abundance`, `size`, `location`, `type`, `presence`, study-design words (`site location`,
   `plot`, `year`, `data analysis`), and species or place names. Prefer two or more words. A single word is
   fine only if it is an unambiguous technical term (e.g. `escapement` for fish returning to spawn).
3. It respects the near-miss boundaries in the header: native vs non-native, survival vs growth, cover vs
   richness, plant vs animal. A term that could fall on either side is rejected.
4. It is not already covered: no existing label or synonym of any class already matches it.
5. Generic classes (`restoration_general`, `site_conditions`, `population_size_trend`, `harvest_general`,
   `tree_species_composition`, `diversity_indices`, `functional_recovery`, `land_use`) only when the term
   is unmistakably that and nothing more specific fits.
6. If `types` is only `management_intervention`, the class must be a cause class.

`phrase` is the term itself or a shorter core that is still specific (e.g. term `wood ash application rate`
-> phrase `wood ash`). You may add a trailing `*` for word endings. Never broaden beyond what the term
means. When in doubt, reject: a missed synonym costs little, a wrong one costs a lot.

## Output

Write `audit/out_NNNN.jsonl` (same NNNN), exactly one line per input line, same order:

`{"id": "T0001", "term": "cover", "class": null, "phrase": null, "why": "generic"}`
`{"id": "T0042", "term": "co2 production", "class": "carbon_flux", "phrase": "co2 production", "why": "..."}`

`class` and `phrase` are both null (reject) or both set (accept). `class` must be an existing id. Keep
`why` under 12 words.
