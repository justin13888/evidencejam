"""ROADMAP item 1: trap inventory with counts and checkable examples.

    python experiments/profile/traps.py

Writes experiments/results/trap_inventory.json. Each trap is a way a naive reader of this graph gets
the direction, null-vs-effect or certainty wrong; the examples seed tagged dev items for items 7 and 9.
Signs come only from camoreasoning.signs (the schema's convention); this script sets no answer policy.
Deterministic: examples are the first edges in graph order.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from common import NEGATIVE_QUALIFIERS, SIGNED_QUALIFIERS, concept, example, label, write_json

from camoreasoning.graph import load_graph
from camoreasoning.profile import profile_graph
from camoreasoning.signs import is_null_finding, predicate_sign, variable_level_sign

N_EX = 5
UNSIGNED_STRUCTURAL = ("moderates", "mediates", "regulates", "precedes")
NEAR_MISS = {
    "native_vs_nonnative": (
        r"(?<!non-)(?<!non)\bnative\b",
        r"\b(non-?native|exotic|invasive|alien|introduced species|weed)",
    ),
    "survival_vs_growth": (r"\bsurviv|\bmortality\b", r"\bgrowth\b|\bheight\b|\bdiameter\b|\bbiomass\b"),
    "cover_vs_richness": (r"\bcover\b", r"\brichness\b|\bdiversity\b"),
    "abundance_vs_richness": (r"\babundance\b|\bdensity\b", r"\brichness\b|\bdiversity\b"),
    "cover_vs_biomass": (r"\bcover\b", r"\bbiomass\b"),
    "germination_vs_establishment": (r"\bgerminat|\bemergence\b", r"\bestablish"),
    "co2_vs_methane": (r"\bco2\b|carbon dioxide|\bnee\b|\bgep\b", r"methane|\bch4\b"),
}


def pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


def trap(count: int, ids, g, why: str, handle: str, **sub) -> dict:
    ids = list(ids)
    return {"count": count, "share_of_edges_pct": pct(count, len(g.edges)), "why": why, "handled_by": handle,
            **({"breakdown": sub} if sub else {}), "examples": [example(g, e) for e in ids[:N_EX]]}  # fmt: skip


def counted(c: Counter) -> dict:
    return {str(k): v for k, v in sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0])))}


def main() -> None:  # noqa: C901, PLR0915 - one linear inventory, kept in one place for review
    g = load_graph()
    prof = profile_graph(g)
    E, N = g.edges, g.nodes
    order = list(E)
    subj = {e: N[E[e]["subject"]] for e in order}
    obj = {e: N[E[e]["object"]] for e in order}
    q = lambda n: n.get("state_or_change_qualifier")  # noqa: E731
    nulls = [e for e in order if is_null_finding(E[e])]
    psign = {e: predicate_sign(E[e].get("predicate")) for e in order}
    vsign = {e: variable_level_sign(E[e], subj[e], obj[e]) for e in order}
    out: dict = {"graph": prof["counts"]}

    # 1. Reversed edges ---------------------------------------------------------------------------------
    cpair = {e: (concept(subj[e]), concept(obj[e])) for e in order}
    pairs = defaultdict(list)
    for e in order:
        pairs[cpair[e]].append(e)
    both = sorted({tuple(sorted(p)) for p in pairs if (p[1], p[0]) in pairs and p[0] != p[1]})
    ent = lambda n: label(n, "entity_term") or n["name"].lower()  # noqa: E731
    epairs = defaultdict(list)
    for e in order:
        epairs[(ent(subj[e]), ent(obj[e]))].append(e)
    eboth = sorted({tuple(sorted(p)) for p in epairs if (p[1], p[0]) in epairs and p[0] != p[1]})
    eboth_ids = [e for a, b in eboth for e in (*epairs[(a, b)], *epairs[(b, a)])]
    dual = {c for c, _ in cpair.values()} & {c for _, c in cpair.values()}
    dual_ids = [e for e in order if cpair[e][1] in dual]
    outcome_types = ("environmental_variable", "taxon")
    into_intervention = [e for e in order if obj[e].get("entity_type") == "management_intervention"]
    outcome_drives = [e for e in order if subj[e].get("entity_type") in outcome_types]
    taxon_subject = [e for e in order if subj[e].get("entity_type") == "taxon"]
    out["reversed_edges"] = trap(
        len(eboth_ids), eboth_ids + dual_ids, g,
        "A question asks X -> Y but the graph may hold Y -> X. Raw node pairs almost never appear both ways, so "
        "the risk is a question written in reverse (gold: no_evidence, reverse edges named in searched_for) and "
        "class-level reversal once concepts are merged (re-count after item 3). Roles must be kept.",
        "linker (role-aware pairs), retriever (report reverse edges in searched_for)",
        concept_pairs_with_both_directions=len(both),
        entity_pairs_with_both_directions=len(eboth),
        edges_in_entity_pairs_with_both_directions=len(eboth_ids),
        concepts_used_as_both_cause_and_outcome=len(dual),
        edges_whose_outcome_concept_is_also_a_cause=len(dual_ids),
        edges_with_outcome_type_subject=len(outcome_drives),
        edges_with_taxon_subject=len(taxon_subject),
        edges_with_intervention_object=len(into_intervention),
    )  # fmt: skip

    # 2. Null != decrease --------------------------------------------------------------------------------
    negated = {e for e in order if E[e].get("negated")}
    no_rel = {e for e in order if E[e].get("causal_language") == "no_relationship"}
    null_dec_obj = [e for e in nulls if q(obj[e]) in NEGATIVE_QUALIFIERS]
    null_signed_obj = [e for e in nulls if q(obj[e]) in SIGNED_QUALIFIERS]
    out["null_is_not_decrease"] = trap(
        len(nulls), null_dec_obj + nulls, g,
        "Negated / no_relationship edges are tested-and-found-nothing findings (direction no_effect), not "
        "decreases; a 'decreased' object qualifier on a negated edge still means no effect was found.",
        "interpreter (null votes), aggregator (no_effect vs mixed)",
        negated=len(negated), no_relationship=len(no_rel), negated_and_no_relationship=len(negated & no_rel),
        negated_only=len(negated - no_rel), no_relationship_only=len(no_rel - negated),
        null_by_predicate=counted(Counter(E[e]["predicate"] for e in nulls)),
        null_by_object_qualifier=counted(Counter(str(q(obj[e])) for e in nulls)),
        null_with_negative_object_qualifier=len(null_dec_obj),
        null_with_any_signed_object_qualifier=len(null_signed_obj),
        null_by_certainty_grade=counted(Counter(E[e].get("certainty_grade") for e in nulls)),
    )  # fmt: skip

    # 3. Associational != causal -------------------------------------------------------------------------
    assoc_preds = ("associated_with", "correlated_with")
    assoc = [e for e in order if E[e]["predicate"] in assoc_preds and not is_null_finding(E[e])]
    assoc_both_signed = [e for e in assoc if q(subj[e]) in SIGNED_QUALIFIERS and q(obj[e]) in SIGNED_QUALIFIERS]
    assoc_obj_signed = [e for e in assoc if q(obj[e]) in SIGNED_QUALIFIERS]
    causal_pred_assoc_lang = [e for e in order if psign[e] is not None and E[e]["causal_language"] == "associational"]
    assoc_pred_causal_lang = [e for e in assoc if E[e]["causal_language"] == "direct_causal"]
    out["associational_is_not_causal"] = trap(
        len(assoc), assoc_both_signed + assoc, g,
        "associated_with / correlated_with have no predicate sign; any direction comes only from endpoint "
        "qualifiers and must be worded as association, never 'X increases Y'.",
        "interpreter (qualifier-only sign), grader (lower certainty), renderer (association wording)",
        language_by_predicate={p: counted(Counter(E[e]["causal_language"] for e in order if E[e]["predicate"] == p))
                               for p in sorted({E[e]["predicate"] for e in order})},
        associational_predicate_non_null=len(assoc),
        associational_with_both_qualifiers_signed=len(assoc_both_signed),
        associational_with_signed_object_qualifier=len(assoc_obj_signed),
        signed_predicate_but_associational_language=len(causal_pred_assoc_lang),
        associational_predicate_but_direct_causal_language=len(assoc_pred_causal_lang),
    )  # fmt: skip

    # 4. Negative-qualifier subjects (removed / decreased / absent / ...) --------------------------------
    neg_subj = [e for e in order if q(subj[e]) in NEGATIVE_QUALIFIERS and not is_null_finding(E[e])]
    flipped = [e for e in order if psign[e] is not None and vsign[e] is not None and psign[e] != vsign[e]
               and not is_null_finding(E[e])]  # fmt: skip
    neg_subj_flip = [e for e in neg_subj if e in set(flipped)]
    neg_obj_flip = [e for e in flipped if q(obj[e]) in NEGATIVE_QUALIFIERS]
    out["negative_subject_qualifiers"] = trap(
        len(neg_subj), neg_subj_flip + neg_subj, g,
        "'removal of X causes increased Y' means X lowers Y. Edge sign = subject x predicate x object sign; "
        "reading the predicate alone flips the answer.",
        "node_labeler (polarity), interpreter (sign composition)",
        by_subject_qualifier=counted(Counter(q(subj[e]) for e in neg_subj)),
        negative_subject_and_signed_predicate=sum(psign[e] is not None for e in neg_subj),
        naive_predicate_sign_flipped_total=len(flipped),
        flipped_by_negative_subject=len(neg_subj_flip),
        flipped_by_negative_object=len(neg_obj_flip),
        signed_edges_total=prof["predicate_sign_vs_variable_level"],
    )  # fmt: skip
    assert len(flipped) == prof["predicate_sign_vs_variable_level"].get("disagree"), "flip count drifted"

    # 5. unchanged != null ---------------------------------------------------------------------------------
    unch_subj = [e for e in order if q(subj[e]) == "unchanged"]
    unch_obj = [e for e in order if q(obj[e]) == "unchanged"]
    unch_obj_not_null = [e for e in unch_obj if not is_null_finding(E[e])]
    unch_nodes = [n for n in N.values() if q(n) == "unchanged"]
    out["unchanged_is_not_null"] = trap(
        len(set(unch_subj) | set(unch_obj)), unch_obj_not_null + unch_subj, g,
        "An 'unchanged' endpoint has no variable-level sign but the edge is not negated: 'X causes no change "
        "in Y' reads like a null yet is tagged as a positive claim. Decide explicitly how it votes.",
        "interpreter (unsigned, possibly null-like), aggregator",
        unchanged_nodes=len(unch_nodes),
        edges_with_unchanged_subject=len(unch_subj),
        edges_with_unchanged_object=len(unch_obj),
        unchanged_object_and_not_negated=len(unch_obj_not_null),
        unchanged_object_and_negated=len(unch_obj) - len(unch_obj_not_null),
        unchanged_object_by_predicate=counted(Counter(E[e]["predicate"] for e in unch_obj)),
        unchanged_object_by_language=counted(Counter(E[e]["causal_language"] for e in unch_obj)),
    )  # fmt: skip

    # 6. Twin edges from one sentence ---------------------------------------------------------------------
    sent = defaultdict(list)
    for e in order:
        sent[(E[e]["source_document"], (E[e].get("original_sentence") or "").strip())].append(e)
    multi = {k: v for k, v in sent.items() if len(v) > 1}
    same_pair = {k: v for k, v in multi.items() if len({cpair[e] for e in v}) < len(v)}
    null_and_effect = {
        k: v
        for k, v in multi.items()
        if any(is_null_finding(E[e]) for e in v) and not all(is_null_finding(E[e]) for e in v)
    }
    conflicting = {k: v for k, v in multi.items()
                   if any(len({vsign[e] for e in v if cpair[e] == p and vsign[e] is not None}) > 1
                          for p in {cpair[e] for e in v})}  # fmt: skip
    first = lambda d: [e for v in d.values() for e in v][: N_EX * 2]  # noqa: E731
    out["twin_edges_one_sentence"] = trap(
        sum(len(v) for v in multi.values()), first(same_pair) + first(multi), g,
        "One sentence is often split into several edges (one per outcome, or the same claim twice). Counting "
        "each as a separate study inflates evidence; twins can also disagree (one null, one effect).",
        "aggregator (one vote per study), citer (dedupe), grader (study count)",
        sentences_total=len(sent),
        sentences_with_2plus_edges=len(multi),
        edges_in_multi_edge_sentences=sum(len(v) for v in multi.values()),
        sentences_with_repeated_concept_pair=len(same_pair),
        sentences_with_null_and_non_null_edges=len(null_and_effect),
        sentences_with_conflicting_signs_on_one_pair=len(conflicting),
        edges_per_sentence=counted(Counter(min(len(v), 10) for v in sent.values())),
    )  # fmt: skip

    # 7. Moderators / mediators -----------------------------------------------------------------------------
    struct = [e for e in order if E[e]["predicate"] in UNSIGNED_STRUCTURAL]
    out["moderators_mediators"] = trap(
        len(struct), struct, g,
        "moderates / mediates / regulates have no sign: the subject changes or carries another effect. They "
        "must not vote on direction, and 'X moderates Y' is not evidence that X changes Y.",
        "interpreter (exclude from votes), renderer (mention as context)",
        by_predicate=counted(Counter(E[e]["predicate"] for e in struct)),
        unsigned_predicates_in_graph=counted(Counter(E[e]["predicate"] for e in order if psign[e] is None)),
    )  # fmt: skip

    # 8. Near-miss classes ---------------------------------------------------------------------------------
    near: dict = {}
    near_ids: list[str] = []
    text = {nid: " ".join(str(n.get(f) or "") for f in ("name", "embedding_text")).lower() for nid, n in N.items()}
    for name, (pa, pb) in NEAR_MISS.items():
        ra, rb = re.compile(pa), re.compile(pb)
        a = {nid for nid, t in text.items() if ra.search(t)}
        b = {nid for nid, t in text.items() if rb.search(t)}
        da = {E[e]["source_document"] for e in order if E[e]["object"] in a}
        db = {E[e]["source_document"] for e in order if E[e]["object"] in b}
        near[name] = {"a": pa, "b": pb, "a_nodes": len(a - b), "b_nodes": len(b - a), "nodes_matching_both": len(a & b),
                      "documents_with_both_as_outcomes": len(da & db)}  # fmt: skip
        near_ids += [e for e in order if E[e]["object"] in (a & b)][:1]
    out["near_miss_classes"] = trap(
        sum(v["nodes_matching_both"] for v in near.values()), near_ids, g,
        "Hidden questions name broad classes; adjacent classes (native vs non-native, survival vs growth, cover "
        "vs richness) share words and papers. Mixing them answers a different question.",
        "taxonomy_builder (separate classes), node_labeler, linker (margin)",
        **near,
    )  # fmt: skip

    # 9. Graph-specific extras ---------------------------------------------------------------------------
    negpred = [e for e in order if psign[e] == -1]
    double_neg = [e for e in negpred if q(obj[e]) in NEGATIVE_QUALIFIERS | {"unchanged"}]
    out["negative_predicates_double_negation"] = trap(
        len(double_neg), double_neg, g,
        "prevents / disrupts carry their own negative sign, but in this graph the object qualifier almost always "
        "restates the drop ('rewetting prevents decreased Kalmia cover' for 'Kalmia cover was lower'). The schema "
        "product (-1)(-1) = +1 then reads 'increase', against the sentence. Graph error vs schema rule: decide "
        "deliberately (item 6) and keep these out of tuning until gold says which reading the hidden set uses.",
        "interpreter (explicit rule), gold_labeler (sentence-based), renderer (quote sentence)",
        by_predicate=counted(Counter(E[e]["predicate"] for e in negpred)),
        by_object_qualifier=counted(Counter(str(q(obj[e])) for e in negpred)),
        negative_predicate_edges=len(negpred),
        with_negative_or_unchanged_object=len(double_neg),
        non_null=sum(not is_null_finding(E[e]) for e in negpred),
    )  # fmt: skip

    iv_neg = [e for e in order if subj[e].get("entity_type") == "management_intervention"
              and q(subj[e]) in NEGATIVE_QUALIFIERS and not is_null_finding(E[e])]  # fmt: skip
    out["intervention_name_vs_fields"] = trap(
        len(iv_neg), iv_neg, g,
        "Intervention nodes with a negative qualifier usually encode the *target* in entity_term/attribute "
        "('Kalmia control with herbicide' = Kalmia cover, decreased). Read entity_term + measured_attribute + "
        "qualifier, not the name; the intervention itself is only in the name.",
        "node_labeler (label from fields, keep intervention from name), linker",
        by_subject_qualifier=counted(Counter(q(subj[e]) for e in iv_neg)),
        intervention_subject_qualifiers=counted(Counter(str(q(subj[e])) for e in order
                                                        if subj[e].get("entity_type") == "management_intervention")),
    )  # fmt: skip

    doc_pair = defaultdict(list)
    for e in order:
        doc_pair[(E[e]["source_document"], cpair[e])].append(e)
    many = {k: v for k, v in doc_pair.items() if len(v) > 1}
    within_conflict = {k: v for k, v in many.items() if len({vsign[e] for e in v if vsign[e] is not None}) > 1
                       or (any(is_null_finding(E[e]) for e in v) and any(vsign[e] for e in v))}  # fmt: skip
    out["one_study_many_edges"] = trap(
        sum(len(v) for v in many.values()), [e for v in within_conflict.values() for e in v], g,
        "One document often has several edges on the same concept pair (sites, years, species). Votes must be "
        "per study; within-study disagreement is not between-study 'mixed'.",
        "aggregator (one vote per document), grader",
        doc_concept_pairs=len(doc_pair), doc_pairs_with_2plus_edges=len(many),
        doc_pairs_with_internal_conflict=len(within_conflict),
        edges_per_doc_pair=counted(Counter(min(len(v), 10) for v in doc_pair.values())),
        edges_per_document=counted(Counter(min(n // 10 * 10, 100) for n in
                                           Counter(E[e]["source_document"] for e in order).values())),
    )  # fmt: skip

    comp = Counter()
    ref_only = []
    for e in order:
        types = {c.get("comparator_type") for c in E[e].get("comparator") or []}
        comp[" + ".join(sorted(str(t) for t in types)) or "(none)"] += 1
        if types == {"reference_undisturbed"}:
            ref_only.append(e)
    out["comparator_reference"] = trap(
        len(ref_only), ref_only, g,
        "Against a reference (undisturbed) site, 'restored has lower Y' says restoration has not caught up, not "
        "that it lowers Y relative to doing nothing. Direction relative to untreated controls differs.",
        "interpreter (flag), renderer (state comparator), grader",
        comparator_type_sets=counted(comp),
    )  # fmt: skip

    default_sign = [e for e in order if q(subj[e]) in (None, "occurred", "ongoing") and psign[e] is not None]
    out["default_positive_subject"] = trap(
        len(default_sign), default_sign, g,
        "Subjects with no qualifier, 'occurred' or 'ongoing' count as +1 (schema). Fine for interventions; "
        "for a variable like 'time' or 'distance' the direction is 'more X'.",
        "interpreter",
        by_subject_qualifier=counted(Counter(str(q(subj[e])) for e in default_sign)),
        by_subject_entity_type=counted(Counter(str(subj[e].get("entity_type")) for e in default_sign)),
    )  # fmt: skip

    time_subj = [e for e in order if re.search(r"\b(time|year|age|duration)\b", concept(subj[e]))]
    out["time_as_cause"] = trap(
        len(time_subj), time_subj, g,
        "Time / years since treatment is the most frequent cause concept; it is a trajectory, not an intervention, "
        "and should not answer 'what does intervention X do'.",
        "taxonomy_builder (own class), linker",
    )  # fmt: skip

    grade_design = defaultdict(Counter)
    for e in order:
        for t in (E[e].get("evidential_basis") or {}).get("evidence_types", []) or ["(none)"]:
            grade_design[str(E[e].get("certainty_grade"))][t] += 1
    self_loops = [e for e in order if E[e]["subject"] == E[e]["object"]]
    no_type = [nid for nid, n in N.items() if not n.get("entity_type")]
    null_comp = [e for e in order if any(c.get("comparator_type") is None for c in E[e].get("comparator") or [])]
    no_strength = [e for e in order if not E[e].get("strength")]
    dangling = [e for e in order if E[e]["subject"] not in N or E[e]["object"] not in N]
    missing_doc = [e for e in order if E[e]["source_document"] not in g.docs]
    out["certainty_and_records"] = {
        "certainty_grades": counted(Counter(str(E[e].get("certainty_grade")) for e in order)),
        "high_grade_edges": sum(E[e].get("certainty_grade") == "high" for e in order),
        "not_assessed_edges": sum(E[e].get("certainty_grade") == "not_assessed" for e in order),
        "evidence_types_by_grade": {k: counted(v) for k, v in sorted(grade_design.items())},
        "evidence_base_assessment_edges": len(g.meta.get("evidence_base_assessments") or []),
        "graph_top_level_keys": sorted(g.meta),
        "self_loops": self_loops,
        "nodes_without_entity_type": no_type,
        "edges_with_null_comparator_type": null_comp,
        "edges_without_strength": no_strength,
        "dangling_edges": dangling,
        "edges_with_unknown_document": missing_doc,
        "ecosystem_context": prof["edges"]["ecosystem_context"],
    }

    summary = {k: {"count": v["count"], "share_of_edges_pct": v["share_of_edges_pct"]}
               for k, v in out.items() if isinstance(v, dict) and "count" in v}  # fmt: skip
    out = {"summary": summary, **out}
    for v in out.values():
        for ex in v.get("examples", []) if isinstance(v, dict) else []:
            assert ex["edge"] in E
    assert len(nulls) == prof["edges"]["negated"].get("True"), "null count drifted"
    path = write_json("trap_inventory.json", out)
    for k, v in summary.items():
        print(f"{k:32s} {v['count']:6d}  {v['share_of_edges_pct']:5.1f}%")
    print(f"-> {path}")


if __name__ == "__main__":
    main()
