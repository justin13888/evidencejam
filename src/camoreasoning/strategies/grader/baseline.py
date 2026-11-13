"""Median certainty_grade of included edges (lower median)."""

from __future__ import annotations

from camoreasoning.components import Context, Grader
from camoreasoning.contracts import Certainty, Verdict
from camoreasoning.registry import register
from camoreasoning.schema import CERTAINTY_ORDER


@register("grader", "baseline")
class MedianGrade(Grader):
    def grade(self, verdict: Verdict, ctx: Context) -> Certainty | None:
        if verdict.status == "no_evidence":
            return None
        grades = sorted(
            (v.certainty_grade for v in verdict.included if v.certainty_grade in CERTAINTY_ORDER),
            key=CERTAINTY_ORDER.__getitem__,
        )
        return grades[(len(grades) - 1) // 2] if grades else "low"
