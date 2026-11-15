# Experiments

One line per subdirectory: what it tested, whether it won (became a default), and where its numbers are. Shared outputs go to [`results/`](results/). Defaults are in [`src/camoreasoning/strategies/__init__.py`](../src/camoreasoning/strategies/__init__.py).

| Directory | What it tested | Won? | Numbers |
|---|---|---|---|
| [`annotate/`](annotate/) | Not an experiment: inputs, prompts and outputs of the bulk labelling tasks (questions, gold, class questions, class gold). | n/a | `*/merged.jsonl` |
| [`ask/`](ask/) | `./ask.sh --json` on 20 off-template questions against the live endpoint: latency, calls, tokens, linked classes. | Yes: the shapes became `parser/freeform`, the default. | `ask/results.json` |
| [`calibration/`](calibration/) | The fitted `binned` calibrator, scored once on the holdout. | No: holdout ECE 0.187 against a 0.05 target, so the constant 0.6 (`baseline`) ships. | `calibration/holdout_report.json`, `reliability.md` |
| [`devsets/`](devsets/) | Not an experiment: the node-level and class-level gold dev sets, and their audit. | n/a | `devsets/AUDIT.md` |
| [`direction/`](direction/) | `sentence` + `studies` against `baseline` over every cause x outcome class pair, no gold needed. | Yes: `aggregator/studies` is the default; `interpreter/unsigned` builds on `sentence`. | `results/direction_compare.json`, `direction_defaults_*.json` |
| [`embeddings/`](embeddings/) | GloVe static embeddings as a linker fallback (`linker/embed`), and BGE-proposed, audited node-label wording. | GloVe no (links 6 wrong for 1 right). BGE yes: its audited phrases ship in `taxonomy/label_synonyms.yaml`. | `results/embed_*.json`, `results/bge_model_probe.json`, [`bge_synonyms/README.md`](embeddings/bge_synonyms/README.md) |
| [`energy/`](energy/) | Where linking loses dev questions (link ceiling), and a threshold sweep for `linker/nodevote`. | No: `nodevote` lost to `phrase` on both gold sets and is kept non-default. | `results/link_ceiling_*.json`, `results/nodevote_sweep.json` |
| [`gold/`](gold/) | Gold-label rounds for the dev questions and their audits. | n/a (data) | [`gold/README.md`](gold/README.md), `AUDIT.md`, `CLASS.md` |
| [`labels/`](labels/) | Hand audit of the taxonomy node labels over 3 rounds. | Shipped labels; the 90% precision and 80% coverage targets are not both met. | [`labels/node_label_audit.md`](labels/node_label_audit.md) |
| [`linker/`](linker/) | How often a linker maps template questions to the right class pair. | `lexical_v2` went into `phrase`, which `cessation` (the default) extends. | `results/link_probe_*.json` |
| [`llm_profile/`](llm_profile/) | How many questions to batch in one LLM call. | Yes: every fallback question goes in one call. | `results/llm_chunk_size.json` |
| [`profile/`](profile/) | Graph profile: field coverage, vocabularies and the trap inventory. | n/a (analysis) | [`profile/README.md`](profile/README.md), `results/graph_profile.json`, `results/trap_inventory.json` |
| [`release/`](release/) | A 500-question timing set (never scored). | n/a (timing) | see files; timings are in ROADMAP item 22 |
| [`renderer/`](renderer/) | Overclaim review of `renderer/faithful` answers, and a consistency check over every answered result. | Yes: `faithful` is the default. | `renderer/review_20.md` |
| [`results/`](results/) | Not an experiment: the JSON and TSV outputs the other directories write. | n/a | see files |
| [`scoring_variants/`](scoring_variants/) | The same answers scored under each plausible reading of the organizers' scoring, as a best/worst range. | n/a (eval only) | `results/scoring_variants.md`, `.json` |
| [`showcase/`](showcase/) | Not an experiment: builds ~13 judged-run examples covering every visible part of the report (each direction, associational-only, both no_evidence kinds, a wrong answer) with optional screenshots, and diffs them against a snapshot after each change. | n/a (review tooling) | [`showcase/README.md`](showcase/README.md), `snapshot.json` |
| [`traps/`](traps/) | Maps each trap in the inventory to the stage and rule that handles it, and to an end-to-end test. | n/a (tests) | [`traps/README.md`](traps/README.md) |

`verify_node_labels.py` checks `taxonomy/node_labels.jsonl` and draws the samples for `labels/node_label_audit.md`.
