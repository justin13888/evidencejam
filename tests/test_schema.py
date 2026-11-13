"""Pin schema.py tables to schema/causalmosaic.yaml so hardcoded values can never drift."""

import yaml

from camoreasoning import schema
from camoreasoning.config import SCHEMA_PATH


def enums():
    return yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))["enums"]


def test_predicates_match_schema():
    pv = enums()["CausalPredicateEnum"]["permissible_values"]
    got = {k: (v["annotations"]["sign"], v["annotations"]["rosetta_template"]) for k, v in pv.items()}
    assert got == schema.PREDICATES


def test_qualifiers_match_schema():
    pv = enums()["StateOrChangeQualifierEnum"]["permissible_values"]
    got = {k: (v["annotations"]["fcm_sign"], v["annotations"]["rosetta_prefix"]) for k, v in pv.items()}
    assert got == schema.QUALIFIERS


def test_certainty_matches_schema():
    pv = enums()["CertaintyGradeEnum"]["permissible_values"]
    assert tuple(pv) == schema.CERTAINTY_GRADES
    got = {k: v["annotations"]["rosetta_verb_modifier"] for k, v in pv.items() if v.get("annotations")}
    assert got == schema.CERTAINTY_MODIFIER
    assert pv["very_low"]["annotations"]["rosetta_template"].strip() == schema.VERY_LOW_TEMPLATE


def test_causal_language_matches_schema():
    assert tuple(enums()["ClaimStrengthEnum"]["permissible_values"]) == schema.CAUSAL_LANGUAGE
