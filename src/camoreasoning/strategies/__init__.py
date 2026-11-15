"""Open for experiments. Add `<stage>/<name>.py` with `@register(<stage>, <name>)`; select it here or
per run with CAMOREASONING_STRATEGY_<STAGE>=<name>. tests/contracts verifies every registered strategy."""

DEFAULTS: dict[str, str] = {
    "parser": "freeform",
    "linker": "phrase",
    "retriever": "baseline",
    "interpreter": "sentence",
    "aggregator": "studies",
    "grader": "baseline",
    "calibrator": "baseline",
    "citer": "baseline",
    "renderer": "faithful",
    "extras": "gapmap",
    "taxonomy_builder": "baseline",
    "node_labeler": "baseline",
    "devset_builder": "baseline",
    "gold_labeler": "baseline",
}
