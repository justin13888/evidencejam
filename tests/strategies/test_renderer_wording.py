"""#113 and #103: wording of answered and no_evidence text. X and Y are short noun phrases (else the class
label), verbs agree with a plural X, composition outcomes say "a change", surnames are normalised, and an
unparsed question gives one reason in `answer` and `searched_for`. Wording only: status, direction,
certainty and edge_ids are untouched (checked against answers.json before/after, not here)."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
import yaml

from camoreasoning import pipeline, registry
from camoreasoning.config import EXPERIMENTS_DIR, ROOT, Settings
from camoreasoning.contracts import Candidates, EdgeVote, Frame, ParsedQuestion, Question, Ref, Side, Verdict
from camoreasoning.strategies.renderer.consistency import violations
from camoreasoning.strategies.renderer.faithful import _first_author
from camoreasoning.strategies.renderer.searched import UNPARSED, is_plural, noun_phrase
from camoreasoning.taxonomy import TaxonClass

R = registry.get("renderer", "faithful")
B4 = ("What lethal and sub-lethal effects do contaminants such as oil sands tailings, PCBs and acid deposition "
      "have")  # fmt: skip
CLASSES = {
    "tree_seedling_survival": TaxonClass("tree_seedling_survival", "outcome", "seedling & tree survival"),
    "community_composition": TaxonClass("community_composition", "outcome", "community composition & similarity"),
    "contaminants": TaxonClass("contaminants", "cause", "contaminants & pollution"),
    "invasive_removal": TaxonClass("invasive_removal", "cause", "invasive species removal"),
    "plant_richness": TaxonClass("plant_richness", "outcome", "species richness"),
}
DOCS = {
    "d:a": {"authors": ["McLACHLAN, STEPHANE M"], "year": 2001},
    "d:b": {"authors": ["Anne Naeth, M."], "year": 2014},
}
WH = re.compile(r"(?:^|effect of |association between |points to )(what|which|how|when|where|why|who)\b", re.I)


def ctx():
    return SimpleNamespace(graph=SimpleNamespace(docs=DOCS, edges={}, nodes={}),
                           taxonomy=SimpleNamespace(classes=CLASSES))  # fmt: skip


def cands(cause, outcome, cause_cls="invasive_removal", outcome_cls="plant_richness", question=None):
    q = Question("q", question or f"What effect does {cause} have on {outcome}?")
    f = Frame(ParsedQuestion(q, cause, outcome, True), Side(cause, (Ref(cause_cls),)),
              Side(outcome, (Ref(outcome_cls),)), "regex", 1.0)  # fmt: skip
    return Candidates(f, {"n1": 1}, {"n2": 1}, forward=("e",))


def verdict(direction, docs=(("d:a", 1),), assoc=False, status="answered"):
    votes = tuple(
        EdgeVote(f"e{i}", d, e, True, "associational" if assoc else "signed") for i, (d, e) in enumerate(docs)
    )
    return Verdict(status, direction, votes, tuple(docs), 0.5)


def render(v, c, certainty="moderate"):
    return R.render(v, c, certainty, ctx())[0]


# --- 1. span guard ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("span", "question", "want"),
    [("remove buckthorn", "What happens to bird diversity when you remove buckthorn?", "removing buckthorn"),
     ("woody debris to streams", "Does adding woody debris to streams increase fish abundance?",
      "adding woody debris to streams"),
     ("tree seedlings survive", "Does mulching help tree seedlings survive?", None),
     (B4, "", None), ("bird diversity?", "", None), ("fish numbers, growth and survival", "", None),
     ("how wet the soil is", "", None), ("does mulching help", "", None), ("help seedlings", "", None),
     ("prescribed burning", "", "prescribed burning"), ("following woody debris", "", "following woody debris")],
)  # fmt: skip
def test_noun_phrase_guard(span, question, want):
    assert noun_phrase(span, question) == want


def test_bare_verb_cause_becomes_a_gerund_in_no_evidence_text():
    c = cands(
        "remove buckthorn", "bird diversity", question="What happens to bird diversity when you remove buckthorn?"
    )
    v = Verdict("no_evidence", None, (), (), 0.0)
    assert R.render(v, c, None, ctx())[0] == "The graph has no claim that removing buckthorn affects bird diversity."


def test_noun_phrase_ending_in_a_verb_uses_the_class_label():
    c = cands("mulching", "tree seedlings survive", outcome_cls="tree_seedling_survival",
              question="Does mulching help tree seedlings survive?")  # fmt: skip
    text = render(verdict("no_effect", (("d:a", 0),)), c, "low")
    assert text.startswith("Mulching may have no detectable effect on seedling & tree survival (low certainty).")


def test_dropped_gerund_is_restored_from_the_question():
    c = cands("woody debris to streams", "fish abundance",
              question="Does adding woody debris to streams increase fish abundance?")  # fmt: skip
    text = render(verdict("increase"), c)
    assert text.startswith("Adding woody debris to streams probably increases fish abundance")


def test_b4_whole_clause_echo_falls_back_to_labels():
    c = cands(B4, "wildlife and aquatic communities, and do remediation actions allow them to recover",
              cause_cls="contaminants", outcome_cls="community_composition")  # fmt: skip
    text = render(verdict("increase", assoc=True), c, "very_low")
    assert "What lethal" not in text and "?" not in text and "remediation" not in text
    assert "between contaminants & pollution and community composition & similarity" in text


# --- 2. agreement -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("x", "label", "plural"),
    [("instream habitat structures", False, True), ("prescribed burning", False, False), ("grass", False, False),
     ("organic & soil amendments", True, False), ("adding compost or soil amendments", False, False),
     ("abundance of native plants", False, False), ("planting-stock traits", False, True)],
)  # fmt: skip
def test_is_plural(x, label, plural):
    assert is_plural(x, label) is plural


@pytest.mark.parametrize(
    ("direction", "certainty", "assoc", "want"),
    [("increase", "moderate", False, "Instream habitat structures probably increase species richness"),
     ("increase", "high", False, "Instream habitat structures increase species richness"),
     ("increase", "moderate", True, "Instream habitat structures are probably associated with higher"),
     ("no_effect", "moderate", False, "Instream habitat structures probably have no detectable effect"),
     ("no_effect", "high", True, "Instream habitat structures show no detectable association")],
)  # fmt: skip
def test_plural_subject_takes_plural_verb(direction, certainty, assoc, want):
    c = cands("instream habitat structures", "species richness")
    e = {"increase": 1, "no_effect": 0}[direction]
    assert render(verdict(direction, (("d:a", e),), assoc), c, certainty).startswith(want)


def test_singular_subject_unchanged():
    assert render(verdict("increase"), cands("prescribed burning", "species richness")).startswith(
        "Prescribed burning probably increases species richness"
    )


def test_leading_the_reads_a_higher():
    text = render(verdict("increase", assoc=True), cands("canopy shade", "the number of species"), "low")
    assert "associated with a higher number of species" in text


# --- 3. outcomes with no direction ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "direction", "certainty", "assoc", "want"),
    [("species composition", "increase", "moderate", False,
      "Instream habitat structures probably change species composition"),
     ("species composition", "decrease", "low", False, "Instream habitat structures may change species composition"),
     ("which species make up the community", "increase", "very_low", True,
      "being associated with a change in community composition & similarity"),
     ("species composition", "increase", "very_low", False, "but it points to a change in species composition"),
     ("ordination scores", "increase", "moderate", True, "are probably associated with a change in ordination scores")],
)  # fmt: skip
def test_composition_outcomes_say_change(outcome, direction, certainty, assoc, want):
    c = cands("instream habitat structures", outcome, outcome_cls="community_composition")
    e = 1 if direction == "increase" else -1
    v = verdict(direction, (("d:a", e),), assoc)
    text = render(v, c, certainty)
    assert want in text, text
    head = text.split(" Across ")[0]
    assert not re.search(r"\b(higher|lower|increases?|decreases?)\b", head), text
    assert not violations(text, v, assoc, ("instream habitat structures", outcome)), text


# --- 4. author surnames -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("authors", "surname"),
    [(["McLACHLAN, STEPHANE M"], "McLachlan"), (["O'BRIEN, PAT"], "O'Brien"), (["SMITH-JONES, A."], "Smith-Jones"),
     ("Anne Naeth", "Naeth"), (["Anne Naeth, M."], "Naeth"), (["Ellen Marsden, J."], "Marsden"),
     (["Das Gupta, S."], "Das Gupta"), (["Van Wieren, Joshua Frans"], "Van Wieren"),
     (["Grégoire Taillefer, Amélie"], "Grégoire Taillefer"), (["McLachlan, S."], "McLachlan"),
     (["MacKenzie, A."], "MacKenzie"), (["LeBlanc, A."], "LeBlanc")],
)  # fmt: skip
def test_surnames(authors, surname):
    assert _first_author(authors) == surname


def test_breakdown_uses_normalised_surnames():
    text = render(verdict("increase", (("d:a", 1), ("d:b", 1))), cands("prescribed burning", "species richness"))
    assert "(McLachlan 2001; Naeth 2014)" in text


# --- 5. #103: one reason for an unparsed question ---------------------------------------------------------


def test_unparsed_question_gives_one_reason():
    q = Question("q", "Which seed-mix species persist in each ecosite type?")
    c = Candidates(Frame(ParsedQuestion(q, None, None, False), Side(None), Side(None), "none", 0.0), {}, {})
    text, searched = R.render(Verdict("no_evidence", None, (), (), 0.0), c, None, ctx())
    assert text == UNPARSED == ("We couldn't find a cause and an outcome in this question. "
                                'We answer questions like "What effect does X have on Y?"')  # fmt: skip
    assert searched == f"No edge search was run. {UNPARSED}"


def test_parsed_side_that_matched_nothing_says_so():
    q = Question("q", "What effect does moon phase have on species richness?")
    c = Candidates(Frame(ParsedQuestion(q, "moon phase", "species richness", True), Side("moon phase"),
                         Side("species richness", (Ref("plant_richness"),)), "regex", 1.0), {}, {})  # fmt: skip
    text, searched = R.render(Verdict("no_evidence", None, (), (), 0.0), c, None, ctx())
    assert text == "No claim was found because the cause 'moon phase' matched no class or node in the graph."
    assert "'moon phase', which matched no class or node" in searched


# --- sweep: every answered text on the practice, dev and off-template questions ---------------------------


@pytest.mark.parametrize("strategies", [{}, {"parser": "freeform", "linker": "assisted"}], ids=["run", "ask"])
def test_sweep_no_pasted_question_text(strategies, monkeypatch, tmp_path):
    for k in ("BRINE_URL", "BRINE_MODEL", "BRINE_API_KEY", "CAMOREASONING_LLM_CACHE"):
        monkeypatch.delenv(k, raising=False)
    qs = yaml.safe_load((ROOT / "questions.yaml").read_text(encoding="utf-8"))["questions"]
    gold = yaml.safe_load((EXPERIMENTS_DIR / "devsets" / "class_gold.yaml").read_text(encoding="utf-8"))["items"]
    off = yaml.safe_load((EXPERIMENTS_DIR / "ask" / "offtemplate.yaml").read_text(encoding="utf-8"))
    items = [{"id": q["id"], "question": q["question"]} for q in qs + gold + off["items"] + off["unclear"]]
    items += [{"id": f"x{i}", "question": t} for i, t in enumerate([
        "What happens to bird diversity when you remove buckthorn?", "Does mulching help tree seedlings survive?",
        "Does adding woody debris to streams increase fish abundance?"])]  # fmt: skip
    seen = set()
    items = [it for it in items if not (it["id"] in seen or seen.add(it["id"]))]
    qfile, out = tmp_path / "q.yaml", tmp_path / "outputs" / "answers.json"
    out.parent.mkdir()
    qfile.write_text(yaml.safe_dump({"questions": items}))
    pipeline.run_file(qfile, out, Settings(strategies=strategies))
    answers = json.loads(out.read_text())["answers"]
    answered = [a for a in answers if a["status"] == "answered"]
    assert len(answered) > 30
    for a in answered:
        assert "?" not in a["answer"], a
        assert not WH.search(a["answer"]), a
    for a in answers:
        if a["answer"] == UNPARSED:
            assert a["searched_for"].endswith(UNPARSED), a


# --- LLM-linked sides name what the evidence covers -------------------------------------------------------


def test_llm_link_uses_class_labels_not_the_narrower_words_asked():
    """'dogwood' linked by the LLM to a broad outcome class must not be claimed in the answer."""
    c = cands("burning", "dogwood abundance", question="We burned and the dogwood is back. Burn again?")
    c = Candidates(Frame(c.frame.parsed, c.frame.cause, c.frame.outcome, "llm", 1.0), c.cause_nodes,
                   c.outcome_nodes, forward=c.forward)  # fmt: skip
    text = render(verdict("decrease"), c)
    assert "dogwood" not in text.lower()
    assert text.lower().startswith("invasive species removal probably decreases species richness"), text
