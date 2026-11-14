# Gold audit (ROADMAP item 10)

A labeller writes the gold labels: the BRINE endpoint model in round 1, Opus `labeler` agents in
round 2 (see README.md). A fresh model session audits a sample of 40 drawn by trap tag. The auditor
labels each item blind first, then compares its label with the labeller's.

## Steps

1. `PYTHONPATH=src python experiments/gold/review_sample.py -n 40 --seed <new seed>` writes
   `experiments/annotate/gold/review.csv` (the `annotate review-export` format) and `blind.jsonl` (the
   same items, with no model label).
2. The auditor reads only `experiments/annotate/gold/PROMPT.md` (the rubric) and `blind.jsonl`. It
   writes one label per item to `experiments/gold/audit/part<k>_blind.jsonl`, in the same shape the labeller
   uses: `{"id", "status", "direction", "certainty", "edges": [{"ref", "effect"}]}`.
   It never opens `taxonomy/`, `*.meta.jsonl`, `out/`, `merged.jsonl` or pipeline code.
3. The auditor then opens `review.csv` and compares each `model_*` column with its own label.
   - Set `ok` = `y` when status, direction and certainty all match, and no model edge has an effect
     opposite to the auditor's. The model may include fewer or more edges than the auditor.
   - Otherwise set `ok` = `n` and fill every `human_*` column with the auditor's blind label.
     - Lists use `ref:effect; ref:effect`.
     - Use `null` for an empty direction or certainty.
     - Use `;` alone for an empty edge list. A blank cell keeps the model's edges.
   - Set `reviewer` = `llm:<model id>`. Put a one-line reason in `comment`.
   Verdicts go to `experiments/gold/audit/part<k>_verdicts.jsonl` (`{"id", "ok", "comment"}`), and
   `experiments/gold/fold_audit.py --reviewer llm:<model id>` writes them into `review.csv`.
4. `python -m camoreasoning annotate review-import gold` prints the agreement and writes
   `human.jsonl`. `annotate merge gold` then lets the auditor's corrections win.
5. `python -m camoreasoning -s gold_labeler=annotated devset --gold-only` writes
   `experiments/devsets/gold_annotated.yaml`.

The target is at least 85% agreement. Results are in `experiments/gold/README.md`.
