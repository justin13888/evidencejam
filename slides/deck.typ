// Goose Chain, Evidence Jam 2026: a 2–3 minute talk. Build: `mise run build` (in slides/).
// One `== heading` per slide; `#pause` / `#only` / `#alternatives` are the build steps.
// Every number comes from data/metrics.yaml (`m`) or data/example.json (`ex`).
#import "lib.typ": *
#show: editorial-theme

#title-slide[
  #say[
    We're Goose Chain. Our agent answers causal questions about ecological restoration, cites every claim, and in the judged run it never calls an LLM.
  ]
  #stack(
    spacing: 1.3em,
    kicker[Goose Chain · Evidence Jam 2026 · Lane 2],
    stack(
      spacing: 0.45em,
      text(font: display, weight: "bold", size: 2.6em, top-edge: "cap-height", bottom-edge: "baseline")[Zero LLM calls.],
      text(font: display, weight: "bold", size: 2.6em, fill: muted, top-edge: "cap-height", bottom-edge: "baseline")[Every claim cited.],
    ),
    block(width: 80%, text(size: 0.95em)[How we answer causal questions over a restoration evidence graph by finding the right edges, reading them faithfully, and saying "I don't know".]),
    text(font: mono, size: 0.6em, fill: muted)[github.com/justin13888/evidencejam],
  )
]

= The problem

== "What effect does X have on Y?"

#say[
  Every question asks: what effect does X have on Y? The answer lives in a graph of #num(m.graph.edges) claims from #m.graph.papers papers. About a third of questions have no evidence, and saying so is the right answer. We're scored on being right, calibrated, cited, and cheap.
]

#v(0.6fr)
#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1em,
  big(num(m.graph.edges), [causal claims (edges)]), big(str(m.graph.papers), [papers]), big(m.graph.no_evidence_share, [of questions have no evidence at all]),
)
#v(1fr)
#pause
#quiet[Scored on]
#h(0.3em)
#chip[direction] #chip[certainty] #chip[calibration] #chip[citations] #chip[LLM calls (energy)]

== The hard part isn't reasoning. It's finding.

#say[
  So we profiled the graph first. #num(m.graph.pairs_single_doc) of #num(m.graph.pairs_total) concept pairs rest on a single paper. #m.graph.sign_flips signs flip under a naive reading: decreased mortality is good news. And #num(m.graph.nulls) findings are nulls, which are not decreases. So the job is finding the right edges and reading each one the way its sentence reads, with plain rules.
]

#v(0.4fr)
#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1.2em,
  big(num(m.graph.pairs_single_doc), [of #num(m.graph.pairs_total) concept pairs rest on a *single* paper]),
  uncover("2-", big(num(m.graph.sign_flips), [of #num(m.graph.signed_edges) signed claims flip under a naive reading: "decreased mortality" is good news])),
  uncover("3-", big(num(m.graph.nulls), [null findings, and a null is *not* a decrease])),
)
#v(1fr)
#uncover("4-", panel[
  #text(size: 0.9em)[So the job is #alert[retrieval and faithful reading], not clever inference. #quiet[We built plain rules for that.]]
])

= The approach

== Four plain steps, one frozen contract each

#say[
  The pipeline is four plain steps. Read the question. Link each side to a small offline taxonomy: #m.pipeline.classes classes over #m.pipeline.labelled_nodes labelled nodes. Interpret each edge as its sentence reads. Then one vote per study, two thirds to call a direction, graded, cited, and written from a template. Each stage is a frozen contract, so a new idea is one new file.
]

#v(0.4fr)
#strip((
  ([Read], [Split the question into a cause and an outcome.]),
  ([Link], [Map each side to #m.pipeline.classes classes, built offline from #m.pipeline.labelled_nodes nodes.]),
  ([Interpret], [Read each claim the way its sentence reads. A null means "no effect".]),
  ([Decide & cite], [One vote per study; #m.pipeline.direction_share of studies must agree, else "mixed".]),
))
#v(1fr)
#pause
#panel(fill: accent, inset: (x: 1em, y: 0.75em))[
  #text(fill: white, weight: "semibold")[#m.eval.calls_per_question LLM calls · #m.eval.tokens_per_question tokens at question time]
  #h(1fr)
  #text(fill: white, size: 0.62em, font: mono)[new idea = one new strategy file]
]

== Plot twist: the LLM lost

#say[
  We expected the LLM to do the linking. It lost. With the LLM linking, we scored #fmt(m.linking.llm_assisted_acc, d: 3) at #m.linking.llm_assisted_tokens tokens a question. Plain node voting scored #fmt(m.linking.nodevote_acc, d: 3) at zero tokens. Embeddings linked #m.linking.bge_wrong wrong, so they only propose synonyms offline, for an audit to accept.
]

#quiet[Accuracy with each linker, measured on #m.linking.measured_on]
#v(0.4em)
#bar([LLM-assisted], m.linking.llm_assisted_acc, max: 0.6, fill: muted.transparentize(40%), note: [#m.linking.llm_assisted_tokens tokens / question])
#pause
#bar([lexical baseline], m.linking.baseline_acc, max: 0.6, note: [#m.eval.tokens_per_question tokens])
#bar([node voting], m.linking.nodevote_acc, max: 0.6, fill: accent, note: [#m.eval.tokens_per_question tokens])
#v(1fr)
#pause
#panel[
  #text(size: 0.85em)[*Embeddings* linked #m.linking.bge_wrong wrong, so they only *propose* synonyms offline: an audit kept #m.linking.bge_accepted of #num(m.linking.bge_proposed).]
]

== Given the right edges, the engine is right

#say[
  Hand the engine the correct edges and it gets every direction right. End to end, with edges it finds itself, direction is #fmt(m.eval.direction_acc). So retrieval is the bottleneck, and every gain came from finding better. Accuracy on our #m.eval.pooled_n dev questions climbed from #fmt(m.climb.first().acc) to #fmt(m.climb.last().acc, d: 3), still at zero calls.
]

#grid(
  columns: (0.85fr, 2fr),
  column-gutter: 1.6em,
  [
    #big(fmt(m.eval.oracle_direction), [direction right, given the correct edges], size: 2.4em)
    #v(0.3em)
    #big(fmt(m.eval.direction_acc), [direction right, with the edges it finds], color: warn, size: 2.4em)
  ],
  [
    #quiet[#text(size: 0.75em)[Dev accuracy, #m.eval.calls_per_question LLM calls; each bar is a change we kept]]
    #pause
    #climb(m.climb)
    #text(size: 0.5em, fill: muted)[Axis starts at 0. First bar: the earlier #m.eval.first_eval_n\-question dev set; the rest: all #m.eval.pooled_n.]
  ],
)

= The result

== One real answer, and one honest "no"

#say[
  Say you're a restoration manager. Mulch probably decreases invasive species, moderate certainty, two studies, every claim cited. The hedge word comes only from the evidence certainty. And when the graph is silent, as with herbicide and birds, we say so and show exactly what we searched.
]

#let a = ex.answered
#let n = ex.no_evidence
#let card(q, color: accent, body) = panel(stroke: (left: 4pt + color), inset: (x: 0.9em, y: 0.75em))[
  #text(size: 0.6em, fill: muted)[“#q”]
  #v(-0.35em)
  #body
]
#grid(
  columns: (1fr, 1fr),
  column-gutter: 1.1em,
  [
    #kicker[Answered]
    #v(-0.3em)
    #card(a.question, color: accent)[
      #text(size: 0.78em)[#a.answer]
      #v(-0.3em)
      #chip(fill: white)[*#a.direction*] #chip(fill: white)[*#a.certainty* certainty] #chip(fill: white)[#a.edge_ids.len() claims cited] #chip(fill: white)[#a.calls LLM calls]
    ]
  ],
  [
    #pause
    #kicker[Not in the graph]
    #v(-0.3em)
    #card(n.question, color: muted)[
      #text(size: 0.78em)[#n.answer]
      #v(-0.3em)
      #chip(fill: white)[*no_evidence*] #chip(fill: white)[#n.calls LLM calls]
      #v(-0.2em)
      #text(size: 0.5em, fill: muted)[*What we searched:* #n.searched_for]
    ]
  ],
)

== Honest limits

#say[
  Now the honest part. On dev we score #fmt(m.eval.pooled_acc, d: 3). On our single holdout pass, #fmt(m.eval.holdout_acc). Retrieval shows why: it finds #fmt(m.eval.holdout_retrieval_recall) of the right edges there, against #fmt(m.eval.retrieval_recall) on dev. Our fitted confidence also missed on holdout, so we ship a flat #m.calibration.shipped_confidence and publish both misses on a limits page.
]

#v(0.4fr)
#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1.2em,
  big(fmt(m.eval.pooled_acc, d: 3), [accuracy on dev (n = #m.eval.pooled_n)]),
  uncover("2-", big(fmt(m.eval.holdout_acc), [accuracy on one held-back pass (n = #m.eval.holdout_n): edges found drop #fmt(m.eval.retrieval_recall) → #fmt(m.eval.holdout_retrieval_recall)], color: warn)),
  uncover("3-", big(fmt(m.calibration.binned_holdout_ece, d: 3), [calibration error (ECE) of our fitted confidence on held-back data; #fmt(m.calibration.binned_in_sample_ece, d: 3) on dev], color: warn)),
)
#v(1fr)
#uncover("3-", panel[
  #text(size: 0.85em)[So we ship a flat #alert[#m.calibration.shipped_confidence confidence], list every miss on `limits.html`, and never tuned on held-back data.]
])

== Right edges, faithful reading, honest gaps

#say[
  Zero runtime LLM calls. #m.release.questions questions in about two seconds, and it passes on #m.release.arch with the LLM unreachable. A restoration manager gets a cited answer, or a clear "no studies, and here's what we searched". Right edges, faithful reading, honest gaps. Thank you.
]

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1.2em,
  big(str(m.eval.calls_per_question), [LLM calls in the judged run]),
  big([#m.release.seconds s], [for #m.release.questions questions from a fresh clone; passes on #m.release.arch with the LLM unreachable]),
  big([#fmt(m.eval.no_evidence_p) / #fmt(m.eval.no_evidence_r)], [precision / recall when we say "no evidence" (dev)], size: 2em),
)
#v(1fr)
#let thumb(path, alt, label) = [
  #block(height: 4.2em, width: 100%, clip: true, radius: 8pt, stroke: 1pt + rule, place(top + left, block(height: 30em, image(path, width: 100%, alt: alt))))
  #v(-0.5em)
  #text(size: 0.6em, fill: muted, label)
]
#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1.2em,
  thumb("/docs/img/evidence.png", "Screenshot of an evidence page: the answer, then votes by study with quotes and edge IDs", [An evidence page for every answer]),
  thumb("/docs/img/gapmap.png", "Screenshot of the gap map: a grid of interventions by outcomes with study counts and gaps", [A gap map of where evidence is missing]),
  thumb("/docs/img/limits.png", "Screenshot of the limits page: holdout failures by trap tag", [A limits page of where we fail]),
)
