"""Constant confidence per status (placeholder until fitted on the dev set)."""

from __future__ import annotations

from camoreasoning.components import Calibrator, Context
from camoreasoning.contracts import Features
from camoreasoning.registry import register

CONSTANT = {"answered": 0.6, "no_evidence": 0.6}


@register("calibrator", "baseline")
class ConstantCalibrator(Calibrator):
    def confidence(self, features: Features, ctx: Context) -> float:
        return CONSTANT[features.status]
