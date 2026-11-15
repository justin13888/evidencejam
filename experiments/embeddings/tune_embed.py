"""Offline, 0 calls: is `linker/embed`'s fallback right more often than wrong? (ROADMAP 24)

Two probes, both only on sides every lexical step leaves empty:
  synonyms   CASES below: 28 hand-picked synonym swaps (should link, to the expected class). Too easy:
             the independent probe (synonym_probe.py) is the real test.
  dev empty  node dev sides the default linker leaves empty (from experiments/results/link_misses.json);
             right = the class of a gold edge's node on that side, wrong = any other class, skip = no link.
A wrong link on a dev side is worse than a skip: it turns no_evidence into a made-up answer.

Grid: mean-centred vectors or not x MIN_COS x MIN_GAP.

    Needs taxonomy/word_vectors.bin.gz (build_vectors.py) and experiments/results/link_misses.json.
    bash -c '. scripts/env.sh; "$PY" experiments/embeddings/tune_embed.py'
"""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

from camoreasoning.config import load_settings
from camoreasoning.evaluate import load_devsets
from camoreasoning.pipeline import make_context
from camoreasoning.strategies.linker import embed

# (kind, plain wording, synonym wording, expected class)
CASES = [
    ("cause", "prescribed burning", "controlled fires", "prescribed_burning"),
    ("cause", "wildfire", "forest fires", "wildfire"),
    ("cause", "deer browsing", "ungulate herbivory", "grazing_browsing"),
    ("cause", "cattle grazing", "livestock pressure", "grazing_browsing"),
    ("cause", "herbicide application", "chemical weed killer spraying", "herbicide_application"),
    ("cause", "tree shelters", "seedling guards", "tree_protection"),
    ("cause", "nitrogen fertilization", "nitrogen enrichment", "fertilization"),
    ("cause", "invasive species removal", "eradication of exotic plants", "invasive_removal"),
    ("cause", "clearcut harvesting", "clear-felling", "clearcut_harvest"),
    ("cause", "partial harvesting", "commercial thinning", "partial_harvest"),
    ("cause", "climate warming", "global heating", "climate_warming"),
    ("cause", "trampling", "hiker foot traffic", "tourism_recreation"),
    ("cause", "elevated CO2", "carbon dioxide enrichment", "elevated_co2"),
    ("cause", "peatland rewetting", "blocking drainage ditches", "peatland_rewetting"),
    ("outcome", "bird abundance", "avian abundance", "bird_abundance"),
    ("outcome", "amphibian abundance", "frogs and salamanders", "amphibian_reptile"),
    ("outcome", "insect abundance", "arthropod abundance", "insect_invertebrate"),
    ("outcome", "soil microbes", "bacterial communities", "soil_microbial"),
    ("outcome", "methane emissions", "CH4 release", "methane_emissions"),
    ("outcome", "water table level", "groundwater depth", "water_table_level"),
    ("outcome", "seedling survival", "sapling survival", "tree_seedling_survival"),
    ("outcome", "soil erosion", "soil loss", "soil_erosion"),
    ("outcome", "bare ground", "exposed soil", "bare_ground"),
    ("outcome", "plant biomass", "aboveground dry weight", "biomass_productivity"),
    ("outcome", "mammal abundance", "rodent density", "mammal_abundance"),
    ("outcome", "seed germination", "sprouting", "seed_germination_emergence"),
    ("outcome", "fish abundance", "salmonid numbers", "fish_abundance"),
    ("outcome", "species richness", "number of taxa", "plant_richness"),
]

GRID = {"center": (False, True), "MIN_COS": (0.3, 0.4, 0.5, 0.6, 0.7), "MIN_GAP": (0.02, 0.05, 0.1)}


def dev_sides(ctx) -> list[tuple[str, str, set[str]]]:
    """(text, kind, gold classes) for node-dev sides the default linker left empty."""
    misses = json.loads(Path("experiments/results/link_misses.json").read_text())["gold_annotated"]["side_empty"]
    gold = {g.id: g for g in load_devsets([Path("experiments/devsets/gold_annotated.yaml")], split="dev")}
    g_, tax, out = ctx.graph, ctx.taxonomy, []
    for m in misses:
        cause, outcome = re.match(r"What effect does (.+) have on (.+)\?", m["q"]).groups()
        for kind, text, end in (("cause", cause, "subject"), ("outcome", outcome, "object")):
            if m[kind]:
                want = {lb.class_id for e in gold[m["id"]].edge_ids for lb in tax.classes_of(g_.edges[e][end])}
                out.append((text, kind, want))
    return out


def pick(text: str, kind: str, ctx) -> str | None:
    r = embed.nearest(text, kind, ctx)
    if not r or r[0][0] < embed.MIN_COS or r[0][0] - (r[1][0] if len(r) > 1 else 0) < embed.MIN_GAP:
        return None
    return r[0][1]


def main() -> list[dict]:
    rows = []
    for center in GRID["center"]:
        ctx = make_context(load_settings(), out_dir=Path(".cache/energy"))
        embed.CENTER = center
        dev = dev_sides(ctx)
        for cos, gap in itertools.product(GRID["MIN_COS"], GRID["MIN_GAP"]):
            embed.MIN_COS, embed.MIN_GAP = cos, gap
            syn = [pick(s, k, ctx) == want for k, _, s, want in CASES]
            d = [pick(t, k, ctx) for t, k, _ in dev]
            right = sum(p in w for p, (_, _, w) in zip(d, dev, strict=True) if p)
            wrong = sum(1 for p in d if p) - right
            rows.append({"center": center, "MIN_COS": cos, "MIN_GAP": gap, "syn_right": sum(syn),
                         "dev_right": right, "dev_wrong": wrong, "dev_skip": d.count(None)})  # fmt: skip
            print(json.dumps(rows[-1]), flush=True)
    Path("experiments/results/embed_tune.json").write_text(json.dumps(rows, indent=1))
    return rows


if __name__ == "__main__":
    main()
