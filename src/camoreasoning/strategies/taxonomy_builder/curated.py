"""Curated builder: the class inventory is hand-written in taxonomy/curated_classes.yaml (reviewed,
reproducible, 0 LLM calls). Labels are left empty here; the node_labeler stage fills them."""

from __future__ import annotations

from pathlib import Path

import yaml

from camoreasoning.components import Context, TaxonomyBuilder
from camoreasoning.config import TAXONOMY_DIR
from camoreasoning.registry import register
from camoreasoning.taxonomy import KINDS, TaxonClass, Taxonomy

SOURCE = TAXONOMY_DIR / "curated_classes.yaml"


def load_curated(path: Path = SOURCE) -> Taxonomy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    classes: dict[str, TaxonClass] = {}
    for c in raw.get("classes") or []:
        if c["kind"] not in KINDS:
            raise ValueError(f"class {c['id']}: bad kind {c['kind']!r}")
        if c["id"] in classes:
            raise ValueError(f"duplicate class id {c['id']}")
        classes[c["id"]] = TaxonClass(
            id=c["id"],
            kind=c["kind"],
            label=c["label"],
            synonyms=tuple(str(s).lower() for s in c.get("synonyms") or ()),
            description=c.get("description") or "",
        )
    return Taxonomy(classes=classes, version=str(raw.get("version", "1")))


@register("taxonomy_builder", "curated")
class CuratedBuilder(TaxonomyBuilder):
    def build(self, ctx: Context) -> Taxonomy:
        return load_curated()
