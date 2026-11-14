"""Cite every edge the answer rests on, ordered so the first citations span every study (item 13).

CHALLENGE scores cited `edge_ids` as "the edges that bear on the question" and defines them as "the
edges ... your answer rests on". A direction is decided from every included vote, dissenting studies
and same-sentence twins included, so all of them are cited. Filtering to the winning direction or
collapsing twins drops edges that gold lists as relevant (fixture smoke: recall 1.0 -> 0.71 with no
precision gain), so this citer does neither. Precision is decided upstream, by retrieval and the
interpreter's `included` flag.

- status != answered -> [].
- Every included vote's edge, deduplicated.
- Order: round-robin across studies (study order = first appearance among the votes), and within a
  study the strongest certainty grade first, then vote order. A reader, or a cap, sees one edge per
  study before a second edge from any study.
- CAP = 60, above the largest included set over all taxonomy class pairs (55; median 3). Baseline's
  25 truncates about 3% of pairs. 0 LLM calls, deterministic.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import zip_longest

from camoreasoning.components import Citer, Context
from camoreasoning.contracts import EdgeVote, Verdict
from camoreasoning.registry import register
from camoreasoning.schema import CERTAINTY_ORDER

CAP = 60


def _strength(v: EdgeVote) -> int:
    return -CERTAINTY_ORDER.get(v.certainty_grade or "", -1)


@register("citer", "precise")
class StudySpanningCiter(Citer):
    def cite(self, verdict: Verdict, ctx: Context) -> list[str]:
        if verdict.status != "answered":
            return []
        by_doc: dict[str, list[tuple[int, EdgeVote]]] = defaultdict(list)
        for i, v in enumerate(verdict.included):
            by_doc[v.doc_id].append((i, v))
        queues = [[v for _, v in sorted(vs, key=lambda iv: (_strength(iv[1]), iv[0]))] for vs in by_doc.values()]
        ordered = (v.edge_id for row in zip_longest(*queues) for v in row if v is not None)
        return list(dict.fromkeys(ordered))[:CAP]
