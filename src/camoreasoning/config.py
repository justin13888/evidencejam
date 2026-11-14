"""Paths, environment variables and run knobs. Only BRINE_* identify the LLM endpoint."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / "causal_graph.json"
SCHEMA_PATH = ROOT / "schema" / "causalmosaic.yaml"
TAXONOMY_DIR = ROOT / "taxonomy"
EXPERIMENTS_DIR = ROOT / "experiments"
DEVSETS_DIR = EXPERIMENTS_DIR / "devsets"
RESULTS_DIR = EXPERIMENTS_DIR / "results"
CALIBRATION_DIR = EXPERIMENTS_DIR / "calibration"
ANNOTATE_DIR = EXPERIMENTS_DIR / "annotate"
PRODUCT_DIR = ROOT / "product"
OUTPUTS_DIR = ROOT / "outputs"
CACHE_DIR = ROOT / ".cache"

# Runtime stages in pipeline order, then offline stages. Strategy defaults live in strategies/__init__.py.
RUNTIME_STAGES = (
    "parser", "linker", "retriever", "interpreter", "aggregator",
    "grader", "calibrator", "citer", "renderer", "extras",
)  # fmt: skip
OFFLINE_STAGES = ("taxonomy_builder", "node_labeler", "devset_builder", "gold_labeler")
STAGES = RUNTIME_STAGES + OFFLINE_STAGES


@dataclass(frozen=True)
class Settings:
    team: str = "TBD"
    llm_url: str | None = None
    llm_model: str | None = None
    llm_key: str | None = None
    max_calls: int = 8  # hard per-run budget; the judged run should need <= 1
    llm_timeout: float = 120.0
    llm_cache: bool = False  # dev only: replay identical requests from .cache/llm
    taxonomy_dir: Path | None = None  # dev only: run on another taxonomy (e.g. tests/fixtures/taxonomy)
    offline_max_calls: int = 5000  # budget for offline commands (taxonomy, devset, annotate run)
    strategies: Mapping[str, str] = field(default_factory=dict)  # stage -> strategy name overrides

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_url and self.llm_model)


def _path(value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def load_settings(env: Mapping[str, str] | None = None, **overrides) -> Settings:
    """Read settings from the environment. `CAMOREASONING_STRATEGY_<STAGE>=name` selects a strategy."""
    env = os.environ if env is None else env
    prefix = "CAMOREASONING_STRATEGY_"
    strategies = {k[len(prefix) :].lower(): v for k, v in env.items() if k.startswith(prefix) and v}
    s = Settings(
        team=env.get("CAMOREASONING_TEAM") or Settings.team,
        llm_url=env.get("BRINE_URL") or None,
        llm_model=env.get("BRINE_MODEL") or None,
        llm_key=env.get("BRINE_API_KEY") or None,
        max_calls=int(env.get("CAMOREASONING_MAX_CALLS") or Settings.max_calls),
        llm_timeout=float(env.get("CAMOREASONING_LLM_TIMEOUT") or Settings.llm_timeout),
        llm_cache=env.get("CAMOREASONING_LLM_CACHE") == "1",
        taxonomy_dir=_path(env.get("CAMOREASONING_TAXONOMY_DIR")),
        offline_max_calls=int(env.get("CAMOREASONING_OFFLINE_MAX_CALLS") or Settings.offline_max_calls),
        strategies=strategies,
    )
    if overrides:
        merged = {**s.strategies, **overrides.pop("strategies", {})}
        s = Settings(**{**s.__dict__, **overrides, "strategies": merged})
    return s
