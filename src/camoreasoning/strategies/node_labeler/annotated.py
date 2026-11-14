"""Node labels from the annotate harness (experiments/annotate/node_labels/merged.jsonl).

Fill it with `camoreasoning annotate export node_labels` -> label (Claude Code labeler agent or
`annotate run`) -> `annotate check` -> `annotate merge`, then `camoreasoning -s node_labeler=annotated
taxonomy --labels-only`. Labels for classes no longer in the taxonomy are dropped.
"""

from __future__ import annotations

from camoreasoning.annotate import merged
from camoreasoning.components import Context, NodeLabeler
from camoreasoning.registry import register
from camoreasoning.taxonomy import NodeLabel, Taxonomy


@register("node_labeler", "annotated")
class AnnotatedLabels(NodeLabeler):
    def label(self, taxonomy: Taxonomy, ctx: Context) -> list[NodeLabel]:
        out = []
        for row in merged("node_labels"):
            if row["id"] not in ctx.graph.nodes:
                continue
            src = f"annotate:{row.get('by', 'model')}"
            for lb in row.get("labels") or []:
                if lb["class"] in taxonomy.classes and lb["polarity"] in (-1, 0, 1):
                    out.append(NodeLabel(row["id"], lb["class"], lb["polarity"], 1.0, src))
        return out
