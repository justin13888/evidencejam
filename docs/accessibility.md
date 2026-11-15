# Accessibility audit (WCAG 2.2 AA)

Scope: every page `./run.sh` writes under `outputs/`, from `product/page.html` and `product/style.css`: the
question evidence pages, `index.html`, `gapmap.html`, `gapcells.html` and `limits.html`. All are static HTML
with no script.

## How to re-run it

| Check | Command | In `mise run check` |
| --- | --- | --- |
| Static audit of every page the default and baseline extras write, and of `style.css` | `pytest tests/test_accessibility.py` | yes |
| The same audit over `outputs/` | `mise run a11y` | no |
| The static audit plus axe-core 4.14.0 in jsdom 31.0.1 (pinned in `scripts/a11y_audit.py`, installed into `.cache/a11y`) | `mise run a11y:axe` | no: needs node and npm |

The static audit (`scripts/a11y_audit.py`) checks: `lang` on `html`; a non-empty `title`; exactly one `h1`,
first; no skipped heading level; every table has a `caption`, every `th` a `scope`, no `td` in a `thead`;
every scrolling table wrapper is keyboard-focusable and named; unique ids; in-page links and
`aria-labelledby` resolve; every link has text; no `script`. It parses the colour tokens of both schemes from
`style.css` and computes the contrast of every pair the stylesheet draws: 4.5:1 for text (body, muted, links,
links and text on each gap map shade) and 3:1 for table borders and the focus ring.

jsdom does no layout, so axe reports `color-contrast`, `landmark-one-main` and `page-has-heading-one` as
incomplete there. The static audit covers all three: the template's `main` landmark, one `h1`, and computed
contrast.

## What the audit found and fixed

| Finding | Criterion | Fix |
| --- | --- | --- |
| Wide tables scroll inside `.wrap`, which could not take keyboard focus, so a table with no link in it (sign trace, limits tables) could not be scrolled from the keyboard | 2.1.1 Keyboard | `.wrap` gets `tabindex="0"`, `role="region"` and `aria-labelledby` its caption, with a visible focus ring |
| The baseline gap map's top-left header cell was an empty `td` | 1.3.1 Info and Relationships | a scoped `th` naming the row headers |
| Gap map cell links were only as wide as their digit | 2.5.8 Target Size (Minimum) | the link fills the cell's width (at least 1.5rem); centres stay at least 24 px apart |

The audit at the base commit reported 19 findings over the 14 practice-run pages, all the scroller one; it
reports none now. Contrast already passed in both schemes; the lowest pair is `--line` on the light
background at 4.54:1 (3:1 needed).

## Checked by hand

Done by reading the template and the generated markup, and by rendering the pages in headless Firefox at a
320 px wide viewport (`firefox --headless --window-size=320,1400 --screenshot`).

Keyboard (2.1.1, 2.1.2, 2.4.1, 2.4.3, 2.4.7, 2.4.11):

- [x] The first Tab stop is "Skip to content", which becomes visible on focus and moves to `main`.
- [x] Tab order is source order: header link, then the page's links and table scrollers in reading order,
  then nothing in the footer. There is no `tabindex` above 0.
- [x] Every focusable element is a link or a table scroller; there are no widgets, so no keyboard trap.
- [x] Links and scrollers show a 3 px outline in the link colour on `:focus-visible`, at least 3:1 against
  the background in both schemes; nothing sticky or fixed can cover a focused element.
- [x] A focused table scroller scrolls with the arrow keys.

Reflow at 320 px (1.4.10), text spacing and resize (1.4.4, 1.4.12):

- [x] Evidence, index, gap map and limits pages render at 320 px with no page-level horizontal scroll; the
  body text, headings, answer card and lists wrap.
- [x] Only tables scroll sideways, inside their own focusable scroller. Data tables need two dimensions,
  which 1.4.10 exempts.
- [x] Sizes are in `rem` with no fixed heights, so 200% zoom and the 1.4.12 spacing overrides do not clip text.

No meaning by colour alone (1.4.1):

- [x] Gap map shading repeats the printed count; "gap" is printed in every empty cell.
- [x] Counted or not, study votes, statuses and directions are all words, not colours.
- [x] Links in running text are underlined (browser default, not removed).

Other: `lang="en"` on every page (3.1.1); a distinct `title` per page (2.4.2); a `main` landmark and a
`header` and `footer` (1.3.1); every gap map cell link carries a visually hidden "N studies: cause on outcome"
so its purpose is clear out of context (2.4.4).

## Known limits

- The keyboard items above were checked from the markup and the CSS, not with a screen reader.
- The vertical column headers of the gap map rely on `writing-mode`; at 320 px the grid scrolls sideways,
  which 1.4.10 allows for a two-dimensional table.
