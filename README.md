# camoreasoning

Evidence Jam 2026, Lane 2. It answers "what does this intervention do to this outcome?" from the CAMO causal graph, cites the edges it used, and says so when the graph has no evidence. The challenge brief is in [CHALLENGE.md](CHALLENGE.md).

## Run

```sh
./run.sh questions.yaml answers.json
```

Needs `python3` >= 3.10. The first run creates `.venv` from the pinned `requirements.txt`, using uv if it's installed. The LLM is read from `BRINE_URL`, `BRINE_MODEL` and `BRINE_API_KEY`, or from `.env` (see `.env.example`). Besides `answers.json`, it writes one evidence page per question, an index, a gap map and `footprint.json` to `outputs/`.

To ask a single question:

```sh
./ask.sh "What effect does mulch have on invasive species abundance?"
```

## How it works

1. Split the question into a cause and an outcome.
2. Match each side to taxonomy classes, which are built offline into `taxonomy/`. Wording that matches costs no LLM call. Anything left over goes to the LLM in one batched call.
3. Collect the edges from cause nodes to outcome nodes, and read each one with the schema's variable-level sign rule. Null results count as "no effect".
4. Give each study one vote. The vote produces the direction. Certainty comes from the edges' grades, and confidence is calibrated on our dev set. The cited edges and a templated sentence complete the answer. No LLM writes the answers.

## Develop

```sh
mise run setup   # deps + git hooks
mise run check   # lint, tests, run, validate: the gate for every change
mise run eval    # accuracy, calibration and LLM calls per question on experiments/devsets
```

Without mise: `pip install -e . -r requirements-dev.txt && pytest`.

Offline tooling: `python -m camoreasoning annotate …` is the bulk labelling harness (strictly validated JSONL chunks that a strong model fills, plus a CSV round trip for human review). `calibrate` fits the calibrator on gold dev items, and `probe` checks the LLM endpoint. Who owns what, the locked decisions and the self-check targets are in [ROADMAP.md](ROADMAP.md).

To extend it, add a strategy in `src/camoreasoning/strategies/<stage>/<name>.py` and register it with `@register(stage, name)`. The contract tests in `tests/contracts/` pick it up automatically. The stage interfaces are in `src/camoreasoning/components.py`, and the work plan is in [ROADMAP.md](ROADMAP.md).

Commits follow Conventional Commits (`feat(linker): ...`), and hk enforces this.
