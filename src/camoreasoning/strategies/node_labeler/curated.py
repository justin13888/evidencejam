"""Curated node labeller: phrase match on the node's own words, then one batched LLM pass for the rest.

1. Lexical (0 calls). A class matches when one of its label/synonym phrases occurs in the node's `name`,
   plus `entity_term`/`measured_attribute` when those are free text (CURIEs carry no words). Phrases
   ending in `*` match any word ending. Per node the best two matches by phrase length are kept, so a
   long specific phrase ("seedling survival") beats a short generic one ("survival"). Intervention nodes
   only join cause/both classes.
2. LLM (offline only, skipped if `ctx.llm` is not configured). Nodes with no lexical label are sent in
   chunks; the model picks class ids only. Run with CAMOREASONING_MAX_CALLS high enough for the chunks.
3. Polarity is never asked of the LLM. It is the node's qualifier sign (`unchanged` -> 0), flipped to -1
   when the name itself says removed/absent/reduced and no qualifier already carries the sign.
"""

from __future__ import annotations

import re

from camoreasoning.components import Context, NodeLabeler
from camoreasoning.llm import LLMError
from camoreasoning.registry import register
from camoreasoning.signs import qualifier_sign
from camoreasoning.taxonomy import NodeLabel, Taxonomy

CURIE = re.compile(r"^[A-Za-z]+:\S+$")
NEGATIVE_CUE = re.compile(
    r"\b(removal of|removed|exclusion of|exclusion|exclosure|absence of|absent|lack of|without|no|reduced|"
    r"reduction in|lower|less|decreased|decline in|loss of)\b"
)
# Precedence: a specific class beats a generic one; animal classes beat plant-only metrics; a
# "concentration" node is a chemistry measurement whatever organism it was measured in.
GENERIC = {"population_size_trend", "restoration_general", "harvest_general", "tree_species_composition",
           "diversity_indices", "functional_recovery", "site_conditions", "land_use"}  # fmt: skip
ANIMAL = {"bird_abundance", "reproductive_success", "mammal_abundance", "fish_abundance", "amphibian_reptile",
          "insect_invertebrate", "animal_condition", "wildlife_mortality", "soil_fauna", "soil_microbial"}  # fmt: skip
PLANT_ONLY = {"biomass_productivity", "tree_growth", "tree_seedling_survival", "stand_structure",
              "foliar_nutrients", "plant_cover_total"}  # fmt: skip
CONCENTRATION = re.compile(r"\b(concentrations?|residues?|bioaccumulation)\b")
INVERTED = {  # class -> name pattern meaning the opposite end of the class concept
    "tree_seedling_survival": re.compile(r"\bmortality\b"),
    "wildlife_mortality": re.compile(r"\bmortality\b"),
    "water_table_level": re.compile(r"\b(depth|deeper)\b"),
}
EXCLUSION_CLASSES = {"grazing_browsing"}  # "deer exclusion" = grazing absent even if qualifier says occurred
MAX_PER_NODE = 2
CHUNK = 40

SYSTEM = (
    "You label nodes of an ecology evidence graph with classes. Each input line is JSON: "
    '{"id","t":name,"a":measured attribute,"k":entity type}. Reply with one JSON object '
    '{"<id>": ["class_id", ...]} using only class ids from the list below, at most 2 per node, '
    "[] when none fits. Keep near-misses apart: native vs non-native, survival vs growth, cover vs richness, "
    "plant vs animal. Classes:\n"
)


def node_text(n: dict) -> str:
    parts = [str(n.get("name") or "")]
    for f in ("entity_term", "measured_attribute"):
        v = str(n.get(f) or "")
        if v and not CURIE.match(v):
            parts.append(v)
    return " ".join(parts).lower()


def compile_phrases(taxonomy: Taxonomy) -> dict[str, list[tuple[str, re.Pattern]]]:
    out: dict[str, list[tuple[str, re.Pattern]]] = {}
    for c in taxonomy.classes.values():
        pats = []
        for p in {c.label.lower(), *c.synonyms}:
            if not p:
                continue
            body = re.escape(p.rstrip("*")) + (r"\w*" if p.endswith("*") else "")
            pats.append((p, re.compile(rf"(?<![\w-]){body}(?!\w)")))
        out[c.id] = pats
    return out


def polarity(node: dict, class_id: str) -> int:
    q = node.get("state_or_change_qualifier")
    if q == "unchanged":
        return 0
    sign = qualifier_sign(q) or 1
    name = str(node.get("name") or "").lower()
    if class_id in INVERTED and INVERTED[class_id].search(name):
        sign = -sign
    if sign == 1 and q is None and NEGATIVE_CUE.search(name):
        return -1  # no qualifier, but the name itself says removed / absent / reduced
    if sign == 1 and class_id in EXCLUSION_CLASSES and re.search(r"\bexclu", name):
        return -1
    return sign


def _prefer(found: list[tuple[str, int]], text: str) -> list[tuple[str, int]]:
    ids = {c for c, _ in found}
    if CONCENTRATION.search(text) and "water_chemistry" in ids:
        found = [f for f in found if f[0] not in ANIMAL | PLANT_ONLY | GENERIC]
    if ids & ANIMAL:
        found = [f for f in found if f[0] not in PLANT_ONLY]
    if any(c not in GENERIC for c, _ in found):
        found = [f for f in found if f[0] not in GENERIC]
    found.sort(key=lambda x: -x[1])
    if found:  # a second label must be nearly as specific as the first
        found = [f for f in found if f[1] >= 0.7 * found[0][1]]
    return found


def lexical(taxonomy: Taxonomy, nodes: dict[str, dict]) -> dict[str, list[tuple[str, int]]]:
    """node_id -> [(class_id, matched phrase length)] best first."""
    phrases = compile_phrases(taxonomy)
    cause_ok = {c.id for c in taxonomy.of_kind("cause")}
    hits: dict[str, list[tuple[str, int]]] = {}
    for nid, n in nodes.items():
        text = node_text(n)
        found = []
        for cid, pats in phrases.items():
            if n.get("entity_type") == "management_intervention" and cid not in cause_ok:
                continue
            best = max((len(p) for p, rx in pats if rx.search(text)), default=0)
            if best:
                found.append((cid, best))
        found = _prefer(found, text)
        if found:
            hits[nid] = found[:MAX_PER_NODE]
    return hits


@register("node_labeler", "curated")
class CuratedLabeler(NodeLabeler):
    def label(self, taxonomy: Taxonomy, ctx: Context) -> list[NodeLabel]:
        nodes = ctx.graph.nodes
        out: list[NodeLabel] = []
        hits = lexical(taxonomy, nodes) if not taxonomy.empty else {}
        for nid, found in hits.items():
            top = found[0][1]
            for cid, length in found:
                score = 0.9 if length == top else 0.7
                out.append(NodeLabel(nid, cid, polarity(nodes[nid], cid), score, "lexical"))
        if taxonomy.empty or not ctx.llm.available:
            return out
        missing = [nid for nid in nodes if nid not in hits]
        out += self._llm(taxonomy, ctx, missing)
        return out

    def _llm(self, taxonomy: Taxonomy, ctx: Context, node_ids: list[str]) -> list[NodeLabel]:
        system = SYSTEM + "\n".join(f"{c.id}: {c.label} [{c.kind}]" for c in taxonomy.classes.values())
        items = [
            {
                "id": nid,
                "t": ctx.graph.nodes[nid].get("name"),
                "a": ctx.graph.nodes[nid].get("measured_attribute"),
                "k": ctx.graph.nodes[nid].get("entity_type"),
            }
            for nid in node_ids
        ]
        try:
            reply = ctx.llm.batch_json(system, items, chunk=CHUNK, tokens_per_item=24, purpose="node_labeler")
        except LLMError:
            return []
        out = []
        for nid, cids in reply.items():
            if nid not in ctx.graph.nodes or not isinstance(cids, list):
                continue
            for cid in cids[:MAX_PER_NODE]:
                if isinstance(cid, str) and cid in taxonomy.classes:
                    out.append(NodeLabel(nid, cid, polarity(ctx.graph.nodes[nid], cid), 0.6, "llm"))
        return out
