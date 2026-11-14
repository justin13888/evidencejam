# Task: gold-label a question from the graph's own sentences

Input: a question and up to 60 candidate edges (`ref` e1..eN) found by a crude lexical search.
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
- Edges that do not vote: predicates moderates, mediates, precedes, regulates (non-directional), and
  edges whose cause node is `unchanged`. Leave them out of `edges`. (D3)
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
  does (only reversed, non-directional or unchanged-cause edges, or nothing relevant). no_evidence ->
  direction null, certainty null, edges [].
- If the candidates look incomplete for this question, still label what you see and add a "note".
- Only refs offered in that line. No other keys.
