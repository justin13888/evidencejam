"""Sign primitives exactly as CausalPredicateEnum's description defines them. No answer policy here.

Variable level: edge sign = subject fcm_sign x predicate sign x object fcm_sign. A node with no
qualifier, or with `occurred`/`ongoing`, counts as +1; an `unchanged` endpoint has no sign.
"""

from __future__ import annotations

from camoreasoning.schema import PREDICATES, QUALIFIERS

_SIGN = {"positive": 1, "negative": -1}


def predicate_sign(predicate: str | None) -> int | None:
    """+1/-1 for signed predicates; None for unspecified/variable/pathway/modifier/temporal/unknown."""
    return _SIGN.get(PREDICATES.get(predicate or "", ("", ""))[0])


def qualifier_sign(qualifier: str | None) -> int | None:
    """Variable-level node sign: +1/-1; +1 for missing/occurred/ongoing; None for unchanged."""
    if qualifier is None or qualifier in ("occurred", "ongoing"):
        return 1
    if qualifier == "unchanged":
        return None
    return _SIGN.get(QUALIFIERS.get(qualifier, ("", ""))[0], 1)


def compose(*signs: int | None) -> int | None:
    """Product of signs; None if any factor is None."""
    out = 1
    for s in signs:
        if s is None:
            return None
        out *= s
    return out


def variable_level_sign(edge: dict, subject: dict, obj: dict) -> int | None:
    """Schema convention (2). None when unsigned. Negated edges are null findings, not signs."""
    if edge.get("negated"):
        return None
    return compose(
        qualifier_sign(subject.get("state_or_change_qualifier")),
        predicate_sign(edge.get("predicate")),
        qualifier_sign(obj.get("state_or_change_qualifier")),
    )


def is_null_finding(edge: dict) -> bool:
    """A tested-and-found-nothing claim (`negated` <=> `no_relationship`)."""
    return bool(edge.get("negated")) or edge.get("causal_language") == "no_relationship"
