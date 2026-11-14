# CLAUDE.md

- Spec: CHALLENGE.md. Tasks: ROADMAP.md. Stage contracts: src/camoreasoning/components.py, contracts.py.
- Open, edit without asking: `src/camoreasoning/strategies/`, `taxonomy/`, `experiments/`, `product/`, ROADMAP.md (ticks and notes).
- Everything else is frozen: ask first, with a one-sentence reason. Never edit interfaces, contracts, or `tests/contracts|robustness` to make code pass.
- New work = a new strategy in `strategies/<stage>/<name>.py` with `@register`. Make it default in `strategies/__init__.py` only after eval shows it wins.
- Owners, locked decisions (D1–D6), self-check targets: ROADMAP.md. Bulk labelling: `camoreasoning annotate` + `.claude/agents/labeler.md`; `annotate check` must be clean before `merge`.
- Gate: `mise run check` passes. Report `mise run eval` before and after (accuracy, ECE, calls_per_question).
- LLM only through `ctx.llm` (metered, batched). Target <= 1 call per run. No other runtime network.
- Never commit or hardcode BRINE_* or `.env`. Never invent CAMO fields; the schema descriptions define meaning.
- No new dependencies without consent: pinned, judged on ARM64.
- Commits: `<type>(<scope>): <summary>`. Types: feat fix perf refactor test docs chore build ci revert style exp data.
