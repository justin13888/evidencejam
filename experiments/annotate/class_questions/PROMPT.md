# Task: word a broad class pair the way a practitioner asks, and list search terms

Each input line is one cause class and one outcome class, each with a short `label` and a `description`.
Output one JSON line per input:
{"id": <same id>, "cause": ..., "outcome": ..., "cause_terms": [...], "outcome_terms": [...]}

- `paraphrase: false`: copy `cause_label` and `outcome_label` exactly into `cause` and `outcome`.
- `paraphrase: true`: say each label as a restoration manager would (2-8 words, lower case). Keep the same
  breadth and meaning: do not narrow it to one species or method, and do not widen it. Use your own wording
  where a natural alternative exists.
- `cause_terms` / `outcome_terms`: 4-12 short search phrases (1-3 words, lower case) that the nodes of an
  ecological causal graph about this class would use: methods, materials, taxon groups, measured attributes.
  Match the description's breadth. Write them from your own knowledge.
- The question becomes "What effect does <cause> have on <outcome>?" mechanically. Do not answer it.
- Optional "note". No other keys.
