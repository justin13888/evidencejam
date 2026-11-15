# Slides

The talk: a 2–3 minute deck (9 slides, 20 build pages) on how Goose Chain answers causal questions with zero runtime LLM calls.

- **Deck:** [`goose-chain.pdf`](goose-chain.pdf), vendored. It is tagged PDF/UA-1 and builds byte-identically from source.
- **Speaker script:** in each slide's `#say[...]`. `mise run notes` exports it as `goose-chain.pdfpc` for the [pdfpc](https://pdfpc.github.io/) presenter view; the spoken total is about 430 words, roughly 2:40–2:50.

## Build

From this directory:

```sh
mise run build    # deck.typ -> goose-chain.pdf (offline)
mise run watch    # rebuild on save
mise run preview  # every page as .preview/p-NN.png, for review
mise run notes    # speaker notes -> goose-chain.pdfpc
```

The only tool is Typst 0.15.1, pinned in this directory's `mise.toml`, so the root `mise.toml` is untouched. Touying 0.8.0 and its single dependency are vendored in `vendor/packages/`. The Inter and JetBrains Mono fonts (OFL) are vendored in `fonts/`. A build never touches the network and ignores system fonts, so it produces the same PDF on any machine, ARM64 included.

## Edit

| To change | Edit |
|---|---|
| The words on a slide | `deck.typ`: one `== Title` per slide, with `= Section` as the small kicker above it |
| A number | `data/metrics.yaml`. Each value cites its source, and the deck never types a number literally |
| The example answers | `data/example.json`, a snapshot of `camoreasoning.pipeline.ask()` at 0 LLM calls |
| Colours, fonts, components | `lib.typ` |

Numbers were re-measured with `mise run eval`, `eval:class`, `eval:node` and `eval:holdout` at `c7ef4e9`. When a default flips, re-run those and update `metrics.yaml`.

## Why Touying on Typst

We need a vendored PDF built from code with as little boilerplate as possible. We weighed four options:

- **Touying (Typst), chosen.**
  - A slide is a markdown-like heading plus content.
  - It is a single native binary that was already installed through mise.
  - Charts are plain Typst drawn from the YAML, so they can't drift from the data.
  - Build steps (`#pause`, `#only`, `#uncover`, `#alternatives`, `#meanwhile`) become real PDF pages.
  - It writes accessible PDF/UA-1, which fails the build if an image lacks alt text.
- **Marp.** Markdown with even less boilerplate, but export needs Chromium, PPTX output is flat images, charts must be pre-rendered, and no build steps survive export.
- **Slidev.** The best live animation (v-click, magic-move, view transitions), but it needs `node_modules` plus Playwright Chromium. Its PDF and PPTX export flattens every one of those effects, so its main strength disappears in the file we vendor.
- **Pandoc and Beamer.** A heavy LaTeX toolchain and dated looks.

## Animation map

PDF has no transitions (Typst can't emit them), so all motion is build steps. Each one reveals the next beat of the spoken script.

| Slide | Build |
|---|---|
| 2. The question | Headline numbers first, then the five scoring axes |
| 3. The hard part | One graph fact per click, then the takeaway |
| 4. Pipeline | The four steps, then the "0 LLM calls · 0 tokens" stamp |
| 5. The LLM lost | The LLM bar appears alone, then the zero-token linkers overtake it, then the embeddings note |
| 6. Given the right edges | Oracle and end-to-end direction first, then the accuracy climb (zero-based axis) |
| 7. One real answer | The answered card, then the honest `no_evidence` card beside it |
| 8. Honest limits | Dev 0.648, then the 0.41 holdout beside it with its retrieval cause, then the calibration miss |

A fresh-eyes review against the judging rubric shaped the final pass:

- one headline accuracy (pooled dev) throughout, with holdout shown next to it rather than replacing it;
- a zero-based chart axis;
- plain words in place of jargon;
- fewer clicks;
- a line on what a restoration manager actually gets.

## Design

- Light editorial palette taken from `product/style.css`: ink `#1d1f24` on `#fbfbfd`, one indigo accent `#3c31b8`, and red `#b42318` reserved for limits.
- Every text pair is at least 6.3:1 contrast. Bars always print their value, so colour never carries meaning alone.
- Each slide title is a headline sentence, so the deck reads like the subheads of a blog post.
