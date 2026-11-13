"""Human labels only: reads experiments/labels/human.yaml ({items: [{id, status, direction,
certainty, edge_ids}]}). Independent of the answer pipeline by construction."""

from __future__ import annotations

from collections.abc import Sequence

import yaml

from camoreasoning.components import Context, GoldLabeler
from camoreasoning.config import EXPERIMENTS_DIR
from camoreasoning.contracts import DevQuestion, GoldItem
from camoreasoning.registry import register

PATH = EXPERIMENTS_DIR / "labels" / "human.yaml"


@register("gold_labeler", "baseline")
class HumanLabels(GoldLabeler):
    def label(self, items: Sequence[DevQuestion], ctx: Context) -> list[GoldItem]:
        raw = yaml.safe_load(PATH.read_text(encoding="utf-8")) if PATH.exists() else None
        labels = {str(x["id"]): x for x in (raw or {}).get("items", [])}
        out = []
        for it in items:
            if (lb := labels.get(it.id)) and lb.get("status"):
                out.append(GoldItem(
                    id=it.id, question=it.question, status=lb["status"], direction=lb.get("direction"),
                    certainty=lb.get("certainty"), edge_ids=tuple(lb.get("edge_ids") or ()), tags=it.tags,
                    split=it.split, source=f"human:{lb.get('by', '')}",
                ))  # fmt: skip
        return out
