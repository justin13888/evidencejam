// Theme + helpers for deck.typ. Light editorial look; palette from product/style.css.
#import "@preview/touying:0.8.0": *

#let ink = rgb("#1d1f24")
#let muted = rgb("#4b5262")
#let paper = rgb("#fbfbfd")
#let surface = rgb("#f1f2f7")
#let rule = rgb("#d5d8e0")
#let accent = rgb("#3c31b8") // text-safe indigo (>= 7:1 on paper)
#let accent-fill = rgb("#6366f1") // fills only, always with an ink/white label
#let warn = rgb("#b42318") // text-safe red (>= 5:1 on paper)
#let sans = "Inter"
#let display = "Inter Display"
#let mono = "JetBrains Mono"

#let m = yaml("data/metrics.yaml")
#let ex = json("data/example.json")

// 0.6479 -> "0.648"; keeps trailing zeros so columns line up.
#let fmt(x, d: 2) = {
  let s = str(calc.round(x, digits: d))
  if not s.contains(".") { s += "." }
  let (a, b) = s.split(".")
  a + "." + b + "0" * (d - b.len())
}
#let num(n) = {
  // 5554 -> "5,554"
  let s = str(n)
  let out = ""
  for (i, c) in s.clusters().rev().enumerate() {
    if i > 0 and calc.rem(i, 3) == 0 { out = "," + out }
    out = c + out
  }
  out
}

// ---- building blocks -------------------------------------------------------
#let kicker(body) = text(font: mono, size: 0.55em, weight: "medium", fill: accent, tracking: 0.08em, upper(body))
#let quiet(body) = text(fill: muted, body)
#let code(body) = text(font: mono, size: 0.85em, body)

// A big number with a caption under it.
#let big(value, caption, color: accent, size: 3.2em) = stack(
  spacing: 0.75em,
  text(font: display, weight: "bold", size: size, fill: color, top-edge: "cap-height", bottom-edge: "baseline", value),
  text(size: 0.72em, fill: muted, caption),
)

#let chip(body, fill: surface, color: ink) = box(
  fill: fill,
  radius: 999pt,
  inset: (x: 0.7em, y: 0.38em),
  text(size: 0.72em, weight: "medium", fill: color, body),
)

#let panel(body, fill: surface, stroke: none, inset: 0.9em) = block(
  width: 100%,
  fill: fill,
  stroke: stroke,
  radius: 10pt,
  inset: inset,
  body,
)

// One labelled horizontal bar. Value is printed, so colour never carries meaning alone.
#let bar(label, value, max: 1.0, fill: accent-fill, note: none, width: 13em) = grid(
  columns: (8.5em, width, 1fr),
  column-gutter: 0.6em,
  align: (right + horizon, left + horizon, left + horizon),
  text(size: 0.72em, label),
  box(width: 100%, height: 1.15em, fill: surface, radius: 4pt, box(
    width: value / max * 100%,
    height: 100%,
    fill: fill,
    radius: 4pt,
  )),
  [#text(font: mono, weight: "bold", size: 0.8em, fmt(value, d: 3)) #if note != none { text(size: 0.62em, fill: muted, note) }],
)

// Four-step pipeline strip: number, name, plain-words caption.
#let strip(steps) = grid(
  columns: (1fr,) * steps.len(),
  column-gutter: 0.55em,
  ..steps.enumerate().map(((i, s)) => {
    let (name, caption) = s
    block(width: 100%, height: 6.4em, inset: (x: 0.8em, y: 0.75em), radius: 10pt, fill: surface)[
      #text(font: mono, size: 0.55em, fill: accent, str(i + 1))
      #v(-0.55em)
      #text(weight: "semibold", size: 0.85em, name)
      #v(-0.5em)
      #text(size: 0.6em, fill: muted, caption)
    ]
  }),
)

// Climb chart: dots + values per step; `upto` reveals points left to right.
#let climb(points, upto: 99, lo: 0.0, hi: 0.7, h: 8em) = {
  let n = points.len()
  grid(
    columns: (1fr,) * n,
    column-gutter: 0.4em,
    ..points.enumerate().map(((i, p)) => {
      let shown = i < upto
      let frac = (p.acc - lo) / (hi - lo)
      let last = i == n - 1
      box(height: h + 2.6em, width: 100%)[
        #place(bottom + center, dy: -2.6em, box(
          width: 62%,
          height: frac * h,
          radius: (top: 5pt),
          fill: if not shown { surface } else if last { accent } else { accent-fill.transparentize(55%) },
        ))
        #place(bottom + center, dy: -2.6em - frac * h - 0.3em, if shown {
          text(font: mono, weight: "bold", size: 0.72em, fill: if last { accent } else { ink }, fmt(p.acc, d: 3))
        })
        #place(bottom + center, box(height: 2.2em, align(center + top, text(size: 0.52em, fill: muted, p.label))))
      ]
    }),
  )
}

// ---- theme -----------------------------------------------------------------
#let slide(title: auto, ..args) = touying-slide-wrapper(self => {
  let header(self) = none
  let footer(self) = {
    set text(size: 0.48em, fill: muted)
    grid(
      columns: (1fr, auto),
      [Goose Chain · Evidence Jam 2026],
      context utils.slide-counter.display() + " / " + utils.last-slide-number,
    )
  }
  let self = utils.merge-dicts(self, config-page(header: header, footer: footer))
  touying-slide(self: self, ..args)
})

#let title-slide(body) = touying-slide-wrapper(self => {
  let self = utils.merge-dicts(
    self,
    config-common(freeze-slide-counter: true),
    config-page(footer: none, margin: (x: 3.2em, y: 2.6em)),
  )
  touying-slide(self: self, align(left + horizon, body))
})

#let editorial-theme(body) = {
  show: touying-slides.with(
    config-page(
      ..utils.page-args-from-aspect-ratio("16-9"),
      fill: paper,
      margin: (x: 2.6em, top: 1.9em, bottom: 2.2em),
      footer-descent: 0.9em,
    ),
    config-common(
      slide-fn: slide,
      new-section-slide-fn: none,
      zero-margin-footer: false,
      // Each slide shows its section as a kicker and its title as a headline.
      subslide-preamble: self => block(below: 1.1em)[
        #kicker(utils.display-current-heading(level: 1))
        #v(-0.45em)
        #text(font: display, weight: "bold", size: 1.45em, utils.display-current-heading(level: 2))
      ],
    ),
    config-methods(
      init: (self: none, body) => {
        set text(font: sans, size: 22pt, fill: ink, lang: "en")
        set par(leading: 0.55em, spacing: 0.9em)
        show raw: set text(font: mono)
        show strong: set text(weight: "semibold")
        body
      },
      alert: (self: none, it) => text(fill: accent, weight: "semibold", it),
    ),
    config-colors(primary: accent, neutral-lightest: paper, neutral-darkest: ink),
    config-info(title: [Goose Chain: zero LLM calls, every claim cited], author: [Goose Chain]),
  )
  body
}

// Spoken script for the whole slide (all build steps). Exported to pdfpc by `mise run notes`.
#let say(body) = speaker-note(subslide: none, body)
