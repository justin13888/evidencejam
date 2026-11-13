"""camoreasoning: answer intervention -> outcome questions from a CAMO causal graph.

Frozen core (contracts, IO, LLM metering, eval) lives at package level; experiments plug in
under `camoreasoning.strategies` via `registry.register`.
"""

__version__ = "0.1.0"
