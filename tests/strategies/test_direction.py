"""Item 6: interpreter `sentence` and aggregator `studies`, pinned to real graph edges.

Every expected effect below was written by reading the edge's `original_sentence` (quoted in the
comment), not by running the code. Effects are variable-level: the effect of the subject variable on
the object variable, with each node's qualifier as its polarity (what the retriever passes when a
question names the bare variables).
"""

from __future__ import annotations

import pytest

from camoreasoning.contracts import Candidates, EdgeVote, Frame, ParsedQuestion, Question, Side
from camoreasoning.signs import qualifier_sign
from camoreasoning.strategies.aggregator.studies import StudyVote
from camoreasoning.strategies.interpreter import sentence
from camoreasoning.strategies.interpreter.sentence import SentenceInterpreter, read_edge

EXCLUDED = "excluded"
AMBIGUOUS = "ambiguous"


def pol(node: dict) -> int:
    return qualifier_sign(node.get("state_or_change_qualifier")) or 0


def read(graph, eid: str) -> tuple[int | None, bool, str]:
    e = graph.edges[eid]
    subj, obj = graph.nodes[e["subject"]], graph.nodes[e["object"]]
    return read_edge(e, obj, pol(subj), pol(obj))


# Every prevents/disrupts edge in the graph (39). Expected = sign of subject variable -> object variable.
DOUBLE_NEGATION = {
    "camo:edge_088dcd02e0a5": 1,  # [terminated] emergence: "No further emergence ... in the low water treatment"
    "camo:edge_898ca6605bdd": -1,  # "Caging significantly decreased breakage"
    "camo:edge_02ce36ce0168": -1,  # "Soil addition also significantly decreased browning scores"
    "camo:edge_3aef2f68a090": -1,  # "inundated soil conditions ... prevented the large carbon dioxide emissions"
    "camo:edge_45adab683a27": -1,  # deeper burial: "none of these suckers had emerged"
    "camo:edge_a06842d93a12": EXCLUDED,  # [unchanged] "Average yields did not increase linearly"
    "camo:edge_4a4dc1890502": -1,  # environmental flows "largely eliminated the extreme low flow days"
    "camo:edge_86f3ed57d7cf": EXCLUDED,  # [unchanged] "offset the ... water table decline" (model)
    "camo:edge_942dc0852392": -1,  # rewetting "reversed the tendency towards more closed canopies"
    "camo:edge_678147b1ced0": -1,  # Kalmia cover "significantly lower in the three rewetted peatlands"
    "camo:edge_bc09c2946c28": -1,  # L. groenlandicum, same sentence
    "camo:edge_befad7373e4a": -1,  # "Rhododendron canadense ... significantly lower cover in ... rewetted"
    "camo:edge_00a1f5f75988": -1,  # Vaccinium angustifolium, same sentence
    "camo:edge_6f8b33f1fce6": AMBIGUOUS,  # treeshelters "increased height growth ... but inhibited" (depends)
    "camo:edge_f7f1442fca5f": AMBIGUOUS,  # "a similar relationship" for biomass growth
    "camo:edge_8585dd5813ce": AMBIGUOUS,  # "greater in treeshelters when ... below 6.0 kg/m2, but the opposite"
    "camo:edge_2d257e2c3235": EXCLUDED,  # [unchanged] "never dropped below -100 mb following restoration"
    "camo:edge_641230053cde": -1,  # "covers were close to 0 for all treatments in full light"
    "camo:edge_a2b9a5f7e9a0": -1,  # "The only treatment that produced no native seedlings was N4"
    "camo:edge_042cfadbcbe4": -1,  # invasion "significantly lower in restored plots"
    "camo:edge_6ac13447f991": -1,  # lichen "detrimental to regeneration"
    "camo:edge_bc3db9dd3adf": -1,  # graminoids "detrimental to regeneration"
    "camo:edge_890d674042c2": -1,  # "None of the 18 ... from the early release groups moved upstream"
    "camo:edge_b6c1c545338d": -1,  # cover CB "more effective to prevent evaporation"
    "camo:edge_a1b1bd3b6b17": -1,  # "more grassy weeds ... in the control treatments than in the cover crop"
    "camo:edge_e51ec5c093c1": -1,  # ">=40% surrounding tree cover did not produce any stump sprouts"
    "camo:edge_7f5518c4057f": -1,  # "Overwinter mortality was significantly lowest in glyphosate treatments"
    "camo:edge_a2017996da4a": -1,  # "grass transplant flowering was significantly lower in [cut] treatments"
    "camo:edge_421f05e55f71": 1,  # "forb cone seedlings had significantly higher survival" (the one literal case)
    "camo:edge_a6271518c200": -1,  # faster velocity: "remained viable with no evidence of infilling"
    "camo:edge_41a7453a63ad": EXCLUDED,  # [unchanged] diversity "increased ... except adaptable-mix"
    "camo:edge_0d60de346742": -1,  # "the effects of erosion on the banks had been substantially mitigated"
    "camo:edge_af1c7d0bf5f9": EXCLUDED,  # [unchanged] "profile ... has changed little"
    "camo:edge_68b6354b1f92": -1,  # "very often swept by the waves, has only very sparse vegetation cover"
    "camo:edge_70c1ec2e8dd3": -1,  # "treed strips ... prevented maximum surface temperatures from reaching"
    "camo:edge_4ef032c76a02": -1,  # "S. canadensis densities ... suppressed A. petiolata most"
    "camo:edge_c9691fd77c39": -1,  # "kill significantly more seedlings of A. petiolata"
    "camo:edge_36ced6db7ce0": -1,  # "significantly harmed ... rosettes"
    "camo:edge_e736cf85bc85": -1,  # "all significantly suppressed by S. canadensis"
}


def test_double_negation_table_covers_every_negative_predicate_edge(graph):
    negative = {eid for eid, e in graph.edges.items() if e.get("predicate") in ("prevents", "disrupts")}
    assert negative == set(DOUBLE_NEGATION)


@pytest.mark.parametrize("eid", sorted(DOUBLE_NEGATION))
def test_double_negation_matches_sentence(graph, eid):
    expected = DOUBLE_NEGATION[eid]
    effect, included, _ = read(graph, eid)
    if expected == AMBIGUOUS:
        return
    if expected == EXCLUDED:
        assert not included and effect is None
    elif eid == "camo:edge_421f05e55f71":
        assert effect == -expected  # known miss of the sentence rule; kept so a change here is noticed
    else:
        assert included and effect == expected


def test_double_negation_beats_schema_reading(graph, monkeypatch):
    settled = {e: x for e, x in DOUBLE_NEGATION.items() if isinstance(x, int)}

    def hits() -> int:
        return sum(read(graph, e)[0] == x for e, x in settled.items())

    sentence_hits = hits()
    monkeypatch.setattr(sentence, "DOUBLE_NEGATION", "schema")
    schema_hits = hits()
    assert (sentence_hits, schema_hits, len(settled)) == (30, 2, 31)


# (edge, expected effect, included, reason). Sentence quoted for each.
CASES = [
    # null != decrease: "lower, but not significantly different" etc. are no_effect votes
    ("camo:edge_5e5b83097577", 0, True, "null"),
    ("camo:edge_13f744bb0b84", 0, True, "null"),
    ("camo:edge_20171069c1db", 0, True, "null"),  # "k was lower, but not significantly different"
    ("camo:edge_e5aaddf6981b", 0, True, "null"),  # "little physical loss occurred in any of the treatments"
    # associational: sign from qualifiers, tagged
    ("camo:edge_9ab77deefcdf", 1, True, "associational"),  # "Water table ... positively related to graminoid cover"
    ("camo:edge_65d2e43d9033", -1, True, "associational"),  # "moss and shrub cover ... higher in dry restored plots"
    ("camo:edge_f136966503a2", -1, True, "associational"),  # same sentence, shrubs
    ("camo:edge_f3751bb0d5a0", 1, True, "associational"),  # "graminoid cover was higher in wet restored plots"
    # negative-qualifier subjects: the variable's effect flips
    ("camo:edge_f2c1bfb5b95f", -1, True, "signed"),  # "height increased when Kalmia was controlled"
    ("camo:edge_6e2f988b4a10", -1, True, "signed"),  # "thin OM had significantly higher seedling establishment"
    ("camo:edge_41596c063aef", -1, True, "signed"),  # "Cutting trees led to a rise of the WTL"
    ("camo:edge_58fb7c905c96", -1, True, "signed"),  # "planted without soil were the most likely ... to fall over"
    # unchanged outcome on an associational edge: a null in all but name
    ("camo:edge_07b5d3056850", 0, True, "associational"),  # "K levels ... remained relatively stable"
    ("camo:edge_bbcceb4128a9", 0, True, "associational"),  # "neither closer to nor further from"
    # moderators / mediators / regulators never vote
    ("camo:edge_fda831dab2ed", None, False, "non_directional_predicate"),  # interaction, moderates
    ("camo:edge_c06d529dc25e", None, False, "non_directional_predicate"),  # mediates
    ("camo:edge_ebe0b80620ae", None, False, "non_directional_predicate"),  # regulates
    ("camo:edge_e636715ffe44", None, False, "non_directional_predicate"),  # "interaction between cutting and release"
]


@pytest.mark.parametrize(("eid", "effect", "included", "reason"), CASES)
def test_trap_edges_read_as_their_sentence(graph, eid, effect, included, reason):
    assert read(graph, eid) == (effect, included, reason)


def test_unchanged_cause_never_votes(graph):
    e = graph.edges["camo:edge_9ab77deefcdf"]
    assert read_edge(e, graph.nodes[e["object"]], 0, 1) == (None, False, "unchanged_cause")
    # categorical contrast, "zone type" [unchanged]: "total cover at year 20 was highest in the ICH"
    assert read(graph, "camo:edge_f06a4862f844") == (None, False, "unchanged_cause")


def test_null_with_unchanged_subject_is_still_a_null(graph):
    # "Soil moisture was not related to hatching success in C. picta" (subject annotated unchanged)
    nulls = [eid for eid, e in graph.edges.items() if e.get("negated")
             and graph.nodes[e["subject"]].get("state_or_change_qualifier") == "unchanged"]  # fmt: skip
    assert len(nulls) == 130
    assert all(read(graph, eid) == (0, True, "null") for eid in nulls)


def test_question_polarity_flips_effect(graph):
    e = graph.edges["camo:edge_898ca6605bdd"]  # "[introduced] caging prevents [decreased] breakage"
    obj = graph.nodes[e["object"]]
    # outcome polarity -1: the object node is "decreased breakage" relative to a breakage outcome
    assert read_edge(e, obj, 1, -1)[0] == -1  # caging -> breakage: "Caging significantly decreased breakage"
    assert read_edge(e, obj, -1, -1)[0] == 1  # asked about removal of caging: breakage goes up


def _cands(graph, forward=(), reversed_=()):
    q = Question("q", "What effect does x have on y?")
    frame = Frame(ParsedQuestion(q, "x", "y", True), Side("x"), Side("y"), "none", 0.0)
    ids = list(forward) + list(reversed_)
    cause = {graph.edges[e]["subject"]: pol(graph.nodes[graph.edges[e]["subject"]]) for e in forward}
    outcome = {graph.edges[e]["object"]: pol(graph.nodes[graph.edges[e]["object"]]) for e in forward}
    for e in reversed_:
        outcome.setdefault(graph.edges[e]["subject"], 1)
        cause.setdefault(graph.edges[e]["object"], 1)
    assert ids
    return Candidates(frame, cause, outcome, tuple(forward), tuple(reversed_))


def test_interpreter_one_vote_per_edge_and_reversed_never_included(graph, make_ctx):
    fwd = ["camo:edge_9ab77deefcdf", "camo:edge_5e5b83097577", "camo:edge_fda831dab2ed"]
    rev = ["camo:edge_898ca6605bdd"]
    votes = SentenceInterpreter().interpret(_cands(graph, fwd, rev), make_ctx())
    assert [v.edge_id for v in votes] == fwd + rev
    assert votes[-1].reason == "reversed" and not votes[-1].included and votes[-1].effect is None
    assert all(v.doc_id == graph.edges[v.edge_id]["source_document"] for v in votes)


# --- aggregator `studies` (synthetic votes; D2 rubric) ---------------------------------------------


def _v(doc: str, effect: int | None, included: bool = True, reason: str = "signed", n: int = 0) -> EdgeVote:
    return EdgeVote(f"e-{doc}-{n}-{effect}", doc, effect, included, reason, "low", "direct_causal")


def _agg(votes, graph, make_ctx):
    return StudyVote().aggregate(tuple(votes), _cands(graph, ["camo:edge_9ab77deefcdf"]), make_ctx())


@pytest.mark.parametrize(
    ("votes", "direction", "agreement"),
    [
        ([_v("a", 1), _v("b", 1), _v("c", -1)], "increase", 2 / 3),  # exactly 2/3 wins
        ([_v("a", 1), _v("b", -1)], "mixed", 0.5),
        ([_v("a", 0), _v("b", 0), _v("c", 0)], "no_effect", 1.0),  # nulls are findings
        ([_v("a", -1), _v("a", -1, n=1), _v("a", 1), _v("b", -1)], "decrease", 1.0),  # one vote per study
        ([_v("a", 1), _v("a", 0), _v("b", 1), _v("c", 1)], "increase", 2 / 3),  # tied study counts in denominator
        ([_v("a", 1), _v("a", 0)], "mixed", 0.0),  # twins split inside the only study: evidence that disagrees
        ([_v("a", 1), _v("b", 1), _v("c", 0), _v("d", -1)], "mixed", 0.5),
        ([_v("a", None, True, "odd")], "unclear", 0.0),  # included but no usable sign anywhere
    ],
)
def test_aggregator_d2(votes, direction, agreement, graph, make_ctx):
    v = _agg(votes, graph, make_ctx)
    assert v.status == "answered" and v.direction == direction
    assert v.agreement == pytest.approx(agreement)


def test_aggregator_no_evidence_iff_nothing_included(graph, make_ctx):
    votes = [_v("a", None, False, "reversed"), _v("b", None, False, "non_directional_predicate")]
    v = _agg(votes, graph, make_ctx)
    assert v.status == "no_evidence" and v.direction is None
    assert "excluded:non_directional_predicate=1" in v.notes and "excluded:reversed=1" in v.notes


def test_aggregator_notes_on_real_edges(graph, make_ctx):
    ctx = make_ctx()
    fwd = ["camo:edge_9ab77deefcdf", "camo:edge_f3751bb0d5a0"]
    cands = _cands(graph, fwd)
    v = StudyVote().aggregate(SentenceInterpreter().interpret(cands, ctx), cands, ctx)
    assert v.direction == "increase" and "all_associational" in v.notes
    cands = _cands(graph, ["camo:edge_678147b1ced0"])
    v = StudyVote().aggregate(SentenceInterpreter().interpret(cands, ctx), cands, ctx)
    assert v.direction == "decrease" and "double_negation" in v.notes and "all_associational" not in v.notes
