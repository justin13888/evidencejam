"""No-op builder: returns the committed taxonomy unchanged. Replace with a clustering/LLM builder."""

from __future__ import annotations

from camoreasoning.components import Context, TaxonomyBuilder
from camoreasoning.registry import register
from camoreasoning.taxonomy import Taxonomy


@register("taxonomy_builder", "baseline")
class KeepExisting(TaxonomyBuilder):
    def build(self, ctx: Context) -> Taxonomy:
        return Taxonomy(classes=dict(ctx.taxonomy.classes), version=ctx.taxonomy.version)
