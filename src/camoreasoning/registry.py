"""Strategy registry: `@register("linker", "lexical")` on a subclass of the stage's ABC."""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Mapping

from camoreasoning.components import BASES, Stage

_REGISTRY: dict[str, dict[str, type[Stage]]] = {s: {} for s in BASES}
_discovered = False


def register(stage: str, name: str):
    def deco(cls: type[Stage]) -> type[Stage]:
        if stage not in BASES or not issubclass(cls, BASES[stage]):
            raise TypeError(f"{cls.__name__} must subclass {BASES.get(stage, Stage).__name__}")
        if name in _REGISTRY[stage] and _REGISTRY[stage][name] is not cls:
            raise ValueError(f"duplicate strategy {stage}/{name}")
        cls.name = name
        _REGISTRY[stage][name] = cls
        return cls

    return deco


def discover() -> None:
    """Import every module under camoreasoning.strategies so decorators run."""
    global _discovered
    if _discovered:
        return
    import camoreasoning.strategies as pkg

    for mod in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        importlib.import_module(mod.name)
    _discovered = True


def names(stage: str) -> list[str]:
    discover()
    return sorted(_REGISTRY[stage])


def get(stage: str, name: str | None = None, overrides: Mapping[str, str] | None = None) -> Stage:
    """Instantiate a strategy: explicit name > settings override > strategies.DEFAULTS > 'baseline'."""
    discover()
    from camoreasoning.strategies import DEFAULTS

    name = name or (overrides or {}).get(stage) or DEFAULTS.get(stage, "baseline")
    try:
        return _REGISTRY[stage][name]()
    except KeyError:
        raise KeyError(f"no strategy {stage}/{name}; have {sorted(_REGISTRY[stage])}") from None
