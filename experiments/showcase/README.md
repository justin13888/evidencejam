# Showcase: preview the judged outputs

The practice set (`questions.yaml`) has only one answered question, so most of the report never appears in `outputs/`. This builds a small, fixed set of examples that covers every visible part, for UI review and as a regression check after each change.

```sh
python experiments/showcase/build.py            # ~1 s, 0 LLM calls
python experiments/showcase/build.py --shots    # + headless Firefox PNGs: light/dark x 1280/320 px (a few minutes)
python experiments/showcase/build.py --update   # accept the current answers as the new snapshot
python experiments/showcase/build.py --ask "How do I control garlic mustard?"   # + the ask.sh page (1 LLM call)
python experiments/showcase/build.py --readme   # regenerate the committed README screenshots in docs/img/
```

How it works:

1. It runs the current defaults over the **dev** split of `class_gold.yaml`, then `gold_annotated.yaml`, plus `questions.yaml`. It never uses the holdout.
2. It picks the first example for each variant, judged on our output: each direction, associational-only evidence, one study, the most studies, both kinds of `no_evidence` (graph has nothing, or the question wasn't read), a trap we get wrong, a false `no_evidence`, and b4.
3. It runs only those through the judged entry point (`pipeline.run_file`) into `outputs/showcase/`, which is gitignored. The real `outputs/` is untouched.

The run writes the following under `outputs/showcase/`:
- `CATALOG.md`: one row per example with our fields against gold, a page link and what to look at, followed by each question and its answer text.
- `outputs/*.html`: the evidence pages, `index`, `gapmap`, `gapcells` and `limits`.
- `shots/*.png`: written with `--shots`. Files are named `<page>.<light|dark>.<width>.png`.

Each run prints a field-level diff against [`snapshot.json`](snapshot.json): status, direction, certainty, confidence, edge_ids, answer and searched_for. An empty diff means the change didn't move any visible answer. When the picks change (for example, a fix makes a "wrong" example right), the diff shows it as an id removed and an id added.

After a UI change, the loop is: run `build.py --shots`, read the diff, look at the pages or shots, then run `python scripts/a11y_audit.py outputs/showcase/outputs` and `mise run check`.

The README screenshots (`docs/img/*.png`) are committed so they render on GitHub with no network fetch. `--readme` regenerates them from a fresh run at the current defaults: the light scheme at 1280 x 1400 px, with `evidence.png` showing the page for `C-C0004`. Re-run it after any change to the UI or the answer text, then commit the PNGs.
