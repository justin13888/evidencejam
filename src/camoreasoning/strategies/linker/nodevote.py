"""0-call linker: the graph's labelled nodes vote for a class, and the voters become the side.

Hidden questions name broad classes in the organisers' words, not ours, so class labels and synonyms alone
miss most of them (dev: 7 of 59 answerable questions linked on both sides by lexical_v2). The ~6k nodes in
taxonomy/node_labels.jsonl are already mapped to classes offline, so each node name works as a synonym and
no runtime LLM call is needed (ROADMAP 14).

Per question side:
1. An exact label/synonym phrase (lexical_v2 rule 1) wins outright and links the class.
2. Otherwise score every node labelled with a class of this side's kind by IDF-weighted cosine between the
   side's tokens and the node's (name, entity term, measured attribute). The top K nodes at or above
   MIN_SIM vote for their classes, weighted by similarity x label score. Class phrases accepted by the
   baseline ranking add CLASS_WEIGHT x coverage, so taxonomy words still count.
3. The top class must hold MIN_SHARE of the vote, else the side is empty (-> no_evidence).
   MODE "nodes" (default) links only the nodes that voted for it, each with its label polarity: retrieval
   stays close to the question's wording. MODE "class" links the whole class, which pulls in many
   unrelated studies and turns most answers into "mixed" (dev accuracy 0.44 vs 0.54).
Margin = top share - runner-up share.

Tuned on dev only (experiments/energy/sweep_nodevote.py); accuracy is flat for K >= 30.
"""

from __future__ import annotations

import math
from collections import defaultdict

from camoreasoning.components import Context
from camoreasoning.contracts import Ref, Side
from camoreasoning.registry import register
from camoreasoning.strategies.linker.baseline import NODE_FIELDS, _index, _rank
from camoreasoning.strategies.linker.lexical_v2 import EXACT_MARGIN, PhraseLinker, _equal, _phrases
from camoreasoning.strategies.text import tokens

K = 30  # nearest labelled nodes that may vote
MIN_SIM = 0.45  # cosine floor for a node to vote
MIN_SHARE = 0.3  # the top class must hold this share of the vote
CLASS_WEIGHT = 1.5  # a class's own label/synonym match, relative to one node's vote
MODE = "nodes"  # "nodes": link the winning class's voters; "class": link the winning class


def _nodes(ctx: Context) -> dict:
    """kind -> {"nodes": {node id: (tokens, norm, [(class id, label)])}, "inv": token -> node ids}."""
    key = "linker.nodevote"
    if key not in ctx.memo:
        ix = _index(ctx)
        idf, dflt = ix["idf"], ix["default_idf"]
        tax, g = ctx.taxonomy, ctx.graph
        out = {}
        for kind in ("cause", "outcome"):
            ok = {c.id for c in tax.of_kind(kind)}
            nodes, inv = {}, defaultdict(list)
            for nid, n in g.nodes.items():
                labels = [lb for lb in tax.classes_of(nid) if lb.class_id in ok]
                toks = set(tokens(" ".join(str(n.get(f) or "") for f in NODE_FIELDS)))
                if not labels or not toks:
                    continue
                norm = math.sqrt(sum(idf.get(t, dflt) ** 2 for t in toks))
                nodes[nid] = (toks, norm, [(lb.class_id, lb) for lb in labels])
                for t in toks:
                    inv[t].append(nid)
            out[kind] = {"nodes": nodes, "inv": dict(inv)}
        ctx.memo[key] = out
    return ctx.memo[key]


def vote(text: str | None, kind: str, ctx: Context) -> tuple[list[tuple[float, str]], dict[str, list[Ref]]]:
    """([(share, class id)] best first, class id -> voting nodes as Refs). Empty when nothing is close."""
    q = set(tokens(text))
    if not q:
        return [], {}
    ix = _index(ctx)
    idf, dflt = ix["idf"], ix["default_idf"]
    nx = _nodes(ctx)[kind]
    qn = math.sqrt(sum(idf.get(t, dflt) ** 2 for t in q))
    dots = defaultdict(float)
    for t in q:
        w = idf.get(t, dflt) ** 2
        for nid in nx["inv"].get(t, ()):
            dots[nid] += w
    ranked = sorted(((d / (qn * nx["nodes"][nid][1]), nid) for nid, d in dots.items()), reverse=True)
    votes, voters = defaultdict(float), defaultdict(list)
    for sim, nid in ranked[:K]:
        if sim < MIN_SIM:
            break
        for cid, lb in nx["nodes"][nid][2]:
            votes[cid] += sim * lb.score
            voters[cid].append(Ref(nid, lb.polarity, round(sim, 4)))
    pool = {c.id: ix["class_toks"][c.id] for c in ctx.taxonomy.of_kind(kind)}
    for s, cid in _rank(q, pool, ix):
        votes[cid] += CLASS_WEIGHT * s
    total = sum(votes.values())
    shares = sorted(((v / total, c) for c, v in votes.items()), reverse=True) if total else []
    return shares, dict(voters)


@register("linker", "nodevote")
class NodeVoteLinker(PhraseLinker):
    def _side(self, text, kind, ctx, ix):
        if ctx.taxonomy.empty:
            return super()._side(text, kind, ctx, ix)
        q = tuple(tokens(text))
        if q:
            phrases = _phrases(ctx)
            exact = [
                (lab, c.id) for c in ctx.taxonomy.of_kind(kind) for p, lab, wild in phrases[c.id] if _equal(q, p, wild)
            ]
            if exact:
                best = max(lab for lab, _ in exact)
                ids = sorted({cid for lab, cid in exact if lab == best})
                return Side(text, classes=tuple(Ref(i, 1, 1.0) for i in ids)), EXACT_MARGIN
        shares, voters = vote(text, kind, ctx)
        if not shares or shares[0][0] < MIN_SHARE:
            return Side(text), 0.0
        top, cid = shares[0]
        margin = round(top - (shares[1][0] if len(shares) > 1 else 0.0), 4)
        if MODE == "nodes" and voters.get(cid):
            return Side(text, nodes=tuple(voters[cid])), margin
        return Side(text, classes=(Ref(cid, 1, round(top, 4)),)), margin
