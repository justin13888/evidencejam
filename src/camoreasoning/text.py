"""Shared text helpers (strategies and offline tools such as the gold prefilter)."""

from __future__ import annotations

import re

STOP = frozenset(
    "a an the of on in to and or for with by from at as is are be was were does do did what which how "
    "effect effects affect affects have has had that this these those its it their any some".split()
)


def tokens(text: str | None) -> list[str]:
    """Lowercase alphanumeric tokens without stopwords, crude plural stripping."""
    out = []
    for t in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if t in STOP or len(t) < 2:
            continue
        out.append(t[:-1] if len(t) > 4 and t.endswith("s") and not t.endswith("ss") else t)
    return out
