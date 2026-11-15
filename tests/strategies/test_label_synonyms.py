"""Label-only synonyms (taxonomy/label_synonyms.yaml): they place nodes in a class, never link a question.

experiments/embeddings/bge_synonyms: as class synonyms, the same graph wording linked node-specific
question sides to whole classes and node dev fell, while as node labels alone both dev sets rose.
"""

from __future__ import annotations

from camoreasoning.strategies.node_labeler.curated import (
    LABEL_SYNONYMS,
    compile_phrases,
    lexical,
    load_label_synonyms,
)
from camoreasoning.taxonomy import TaxonClass, Taxonomy

TAX = Taxonomy({"fish_abundance": TaxonClass("fish_abundance", "outcome", "fish abundance", ("fish",), "")})
NODE = {"n1": {"name": "Increased escapement of adult spawners", "entity_type": "environmental_variable"}}


def test_label_only_phrase_labels_the_node():
    assert "n1" not in lexical(TAX, NODE)
    assert lexical(TAX, NODE, {"fish_abundance": ["escapement*"]})["n1"][0][0] == "fish_abundance"


def test_label_only_phrases_stay_out_of_the_linker_phrases():
    """linker/phrase calls compile_phrases(ctx.taxonomy) without extras."""
    assert all(p != "escapement*" for p, _ in compile_phrases(TAX)["fish_abundance"])


def test_unknown_class_in_the_file_is_ignored_and_missing_file_is_empty(tmp_path):
    assert load_label_synonyms(tmp_path) == {}
    (tmp_path / LABEL_SYNONYMS).write_text("classes:\n  nope: [x]\n  fish_abundance: [Escapement*]\n")
    extra = load_label_synonyms(tmp_path)
    assert extra["fish_abundance"] == ["escapement*"]
    assert set(compile_phrases(TAX, extra)) == {"fish_abundance"}


def test_committed_file_loads_and_names_only_known_classes():
    from camoreasoning.taxonomy import load_taxonomy

    extra, tax = load_label_synonyms(), load_taxonomy()
    assert extra and set(extra) <= set(tax.classes)
    linker = {p for c in tax.classes.values() for p in (c.label.lower(), *c.synonyms)}
    assert not linker & {p for ps in extra.values() for p in ps}
