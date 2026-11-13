"""CAMO 0.10.0 vocabularies and rendering tables, copied from schema/causalmosaic.yaml.

Hardcoded so the judged run never parses the 4.5k-line schema; tests/test_schema.py pins every value
against the YAML. Never add values that are not in the schema.
"""

from __future__ import annotations

# CausalPredicateEnum: predicate -> (sign annotation, rosetta_template)
PREDICATES: dict[str, tuple[str, str]] = {
    "causes": ("positive", "{subject} causes {object}"),
    "contributes_to": ("positive", "{subject} contributes to {object}"),
    "associated_with": ("unspecified", "{subject} is associated with {object}"),
    "prevents": ("negative", "{subject} prevents {object}"),
    "enables": ("positive", "{subject} enables {object}"),
    "disrupts": ("negative", "{subject} disrupts {object}"),
    "regulates": ("variable", "{subject} regulates {object}"),
    "mediates": ("pathway", "{subject} mediates the effect on {object}"),
    "moderates": ("modifier", "{subject} moderates the relationship with {object}"),
    "precedes": ("temporal", "{subject} precedes {object}"),
    "correlated_with": ("unspecified", "{subject} is correlated with {object}"),
}

# StateOrChangeQualifierEnum: qualifier -> (fcm_sign, rosetta_prefix)
QUALIFIERS: dict[str, tuple[str, str]] = {
    "increased": ("positive", "increased"),
    "decreased": ("negative", "decreased"),
    "present": ("positive", "presence of"),
    "absent": ("negative", "absence of"),
    "introduced": ("positive", "introduction of"),
    "removed": ("negative", "removal of"),
    "unchanged": ("neutral", "no change in"),
    "occurred": ("neutral", ""),
    "initiated": ("positive", "initiation of"),
    "terminated": ("negative", "cessation of"),
    "ongoing": ("neutral", "continuation of"),
    "interrupted": ("negative", "interrupted"),
    "aborted": ("negative", "aborted"),
}

# CertaintyGradeEnum: grade -> rosetta_verb_modifier ("" = none); very_low uses its own template.
CERTAINTY_MODIFIER: dict[str, str] = {"high": "", "moderate": "probably", "low": "may", "very_low": ""}
VERY_LOW_TEMPLATE = "The evidence is very uncertain about the effect of {subject} on {object}"
CERTAINTY_GRADES = ("high", "moderate", "low", "very_low", "not_assessed")

# ClaimStrengthEnum (slot: causal_language). no_relationship <=> negated: true.
CAUSAL_LANGUAGE = ("no_relationship", "associational", "uncertain_causal", "direct_causal")

ENTITY_TYPES = ("management_intervention", "environmental_variable", "environmental_process", "taxon")

# answers.json vocabularies (README "Answer format").
STATUSES = ("answered", "no_evidence")
DIRECTIONS = ("increase", "decrease", "no_effect", "mixed", "unclear")
ANSWER_CERTAINTY = ("high", "moderate", "low", "very_low")
CERTAINTY_ORDER = {"very_low": 0, "low": 1, "moderate": 2, "high": 3}
