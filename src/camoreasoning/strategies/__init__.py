"""Open for experiments. Add `<stage>/<name>.py` with `@register(<stage>, <name>)`; select it here or
per run with CAMOREASONING_STRATEGY_<STAGE>=<name>. tests/contracts verifies every registered strategy."""

DEFAULTS: dict[str, str] = {
    "parser": "freeform",
    "linker": "baseline",
    "retriever": "baseline",
    "interpreter": "baseline",
    "aggregator": "baseline",
    "grader": "baseline",
    "calibrator": "baseline",
    "citer": "baseline",
    "renderer": "baseline",
    "extras": "baseline",
    "taxonomy_builder": "baseline",
    "node_labeler": "baseline",
    "devset_builder": "baseline",
    "gold_labeler": "baseline",
}
