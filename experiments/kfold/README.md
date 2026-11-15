# k-fold over pooled dev (#120, #82)

`run.py`: one default-pipeline run over pooled dev (class_gold 83 + gold_annotated 184 = 267 items, 0 calls),
then 50 seeds of stratified 5-fold (file x predicted status). Holdout is never read.
Output: `experiments/results/kfold_dev.json`. ECE and Brier come from `evaluate.calibration`, the same 10-bin
scoring as `mise run eval`.

## #120: two-cell calibrator vs constant 0.6

Out-of-fold predictions pooled to one 267-row prediction per seed; mean (5-95% over seeds).

| Calibrator | pooled ECE | pooled Brier | class dev ECE | node dev ECE | per-fold ECE (n ~ 53) |
|---|---|---|---|---|---|
| **baseline 0.6 (shipped)** | 0.048 | 0.230 | **0.087** | **0.030** | 0.059 |
| constant = train accuracy | 0.000 | 0.230 | 0.039 | 0.018 | 0.057 |
| two-cell (status, cap 0.95) | 0.029 (0.000-0.075) | **0.220** | 0.091 (0.085-0.136) | 0.047 (0.038-0.088) | 0.078 |
| binned, refitted per fold | 0.076 (0.051-0.105) | 0.221 | 0.119 | 0.104 | 0.134 |

- Two-cell beats baseline on pooled ECE by 0.019 (88% of seeds), under the ≥0.02 bar in the issue. It
  wins Brier on every seed (0.230 → 0.220): separating answered from `no_evidence` adds
  resolution.
- It loses ECE within each file (class 0.087 → 0.091, node 0.030 → 0.047) and per fold (0.059 → 0.078).
  The pooled win mostly comes from the two files' errors cancelling, and its spread (0.000-0.075) depends
  on which side of a bin edge the two values land.
- Constant = train accuracy has pooled ECE ~0 by construction (one bin), so pooled ECE cannot rank it.
  Its per-file ECE is the best of the four, but it gives no ranking information (Brier = baseline).
- `binned` is worst out of fold, as the holdout already showed (#12).
- **Decision (rule in #120): keep `baseline`.** Two-cell misses the ECE bar and is worse per file. None of
  these fix the shift that matters: unseen questions score ~0.41 (#82), so every dev-fitted level is too high.

## #82: what k-fold can and cannot say

The pipeline has no fitted parameters, so k-fold over dev only re-reads the dev accuracy: it cannot undo
fixes a person made while looking at dev items.

- Pooled dev 0.648, bootstrap 95% CI 0.584-0.708.
- By when an item was labelled (both batches predate every dev-driven fix, #63-#92):

| Batch | gold answered: n / acc | gold no_evidence: n / acc |
|---|---|---|
| gold_annotated, first 142 (11-14 18:41) | 82 / 0.524 | 60 / 0.833 |
| gold_annotated, last 42 (11-14 19:57) | 41 / 0.561 | 1 / 0.000 |
| class_gold, 83 (11-14 19:57) | 48 / 0.542 | 35 / 0.886 |

The later node batch scores 0.548 overall only because it is almost all gold-answered; within status it
matches the earlier batch. So nothing inside dev shows the dev-holdout gap. Holdout (0.41, n = 68, #23 audit)
is below dev in both cells (answered 0.25-0.28, no_evidence recall 0.63-0.75), so it is not just a
different empty share either. Dev cannot settle #82; only the existing holdout number speaks to it.
