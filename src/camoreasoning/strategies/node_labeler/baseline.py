"""Lexical labeller: a node joins a class when a class label/synonym phrase occurs in its text.
Polarity = the node's variable-level qualifier sign (unchanged -> 0)."""

from __future__ import annotations

import re

from camoreasoning.components import Context, NodeLabeler
from camoreasoning.registry import register
from camoreasoning.signs import qualifier_sign
from camoreasoning.taxonomy import NodeLabel, Taxonomy


@register("node_labeler", "baseline")
class PhraseLabeler(NodeLabeler):
    def label(self, taxonomy: Taxonomy, ctx: Context) -> list[NodeLabel]:
        pats = {
            c.id: re.compile(r"\b(" + "|".join(re.escape(p.lower()) for p in (c.label, *c.synonyms) if p) + r")\b")
            for c in taxonomy.classes.values()
        }
        out = []
        for nid, n in ctx.graph.nodes.items():
            text = " ".join(str(n.get(f) or "") for f in ("name", "entity_term", "measured_attribute")).lower()
            pol = qualifier_sign(n.get("state_or_change_qualifier"))
            for cid, rx in pats.items():
                if rx.search(text):
                    out.append(NodeLabel(nid, cid, 0 if pol is None else pol, 1.0, "lexical"))
        return out
