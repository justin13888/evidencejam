# Task: gold-label a class-level question from the graph's own sentences

Input: a broad, class-level question and up to 100 candidate edges (`ref` e1..eN) found by search.
An edge is an instance of a class when its node is a kind or case of it ("straw mulch" is an instance
of "mulch & surface cover"); judge from the node text and the sentence. Many candidates will not fit.
Output one JSON line per input:
{"id": <same id>, "status": "answered"|"no_evidence", "direction": ..., "certainty": ...,
 "edges": [{"ref": "e3", "effect": 1}]}

Rubric (locked decisions, ROADMAP "Decisions"):
- An edge is relevant only if its subject is an instance of the question's cause AND its object an
  instance of the question's outcome. Edges running outcome -> cause are NOT relevant (reversed).
- effect = what the edge says happens to the OUTCOME when the CAUSE is applied/higher, read from the
  sentence: 1 increase, -1 decrease, 0 tested and no effect / no change, null = no usable sign
  (moderator, mediator, pure association with no direction). Watch qualifiers: "removal of X" decreasing Y
  means X increases Y. associated_with/correlated_with count, signed via the qualifiers.
- A null result votes 0 whatever the node qualifiers say: an edge with `negated: true` or
  `language: no_relationship` that is otherwise relevant gets effect 0, even if its cause or outcome node
  is qualified `unchanged` (the schema encodes nulls as negated, never through `unchanged`). (D3)
- Edges that do not vote: predicates moderates, mediates, precedes, regulates (non-directional), and
  non-null edges (`negated: false`) whose cause node is `unchanged`. Leave them out of `edges`. (D3)
- Class membership is strict (round 2). An edge counts only if its node is plainly a kind or case of the
  class as worded. If a narrower neighbouring concept describes the node better, it is not an instance: a
  water table is not soil moisture, plant flowering is not (animal) breeding success, modelled habitat area
  is not fish abundance, and a restoration method that never mentions water is not rewetting.
- Variant-vs-variant contrasts do not vote (round 2). The question asks what the cause does, so an edge
  must compare the cause with its absence, or more of it with less. An edge comparing two kinds of the
  cause (exponential vs conventional fertilization, subsoil type A vs B, soft vs hard release) leaves both
  arms treated: leave it out of `edges`.
- An edge whose outcome is a variance share, an ordination axis, or "explains X% of variation" has no
  usable sign: effect null.
- One vote per study (`study`): the majority effect among that study's listed edges with effect 1, -1 or 0.
  A tie inside one study makes that study internally mixed (it still counts in the denominator). (D2)
- direction: increase / decrease / no_effect if at least 2/3 of studies vote it; otherwise "mixed". Studies
  whose edges all have effect null count for nothing; "unclear" only when every listed edge has effect null.
  If all studies with a sign are internally mixed, direction is "mixed". (D2)
- certainty (D4): the grades of the listed edges, ordered very_low < low < moderate; take the median, and
  with an even count the lower of the two middle grades. Then drop one level (floor very_low) if direction
  is "mixed" OR every listed edge's predicate is associated_with/correlated_with. The `language` field does
  not trigger the drop. Never "high". Do not default to "low": compute it.
- status: "answered" when at least one edge votes (effect 1, -1, 0 or null); "no_evidence" when none
  does (only reversed, non-directional or non-null unchanged-cause edges, or nothing relevant). no_evidence ->
  direction null, certainty null, edges [].
- If the candidates look incomplete for this question, still label what you see and add a "note".
- Only refs offered in that line. No other keys.
