# Judge QA: the 40 judged points

The 40 points are judged subjectively. This file maps them to the repo and records what has already been checked, so nobody re-checks it. Each item is ticked only when it is basically complete. Open items name the issue that tracks the gap.

**Verified at:** master `d25703c`, Sun 2026-11-15. Default strategies: `parser/freeform`, `linker/cessation`, `citer/baseline`, `calibrator/baseline`, `renderer/faithful`, `extras/gapmap`.
**Re-check:** an item if a default for its stage changes (`src/camoreasoning/strategies/__init__.py`), or if the README, `limits.py` or `gapmap.py` change.

## What the judges grade

From CHALLENGE.md and the organizers' rubric:

| Criterion | The judges' question |
|---|---|
| Method and fit | Can the judge explain how it works, and why the approach suits the task? |
| Faithfulness | Does it say only what the sources (the cited edges) support? |
| Honest limits | Does it show where it fails, with examples? Is it honest about uncertainty? |
| Value to a real user | Would the intended user trust it and act on it? |
| Craft and reuse | Could another team pick it up and extend it? |
| Accessibility | Measured against W3C criteria (the slides tie this to Lane 3's prize, so it may not count for Lane 2) |

How judges interact with the submission:
- They read `answers.json` and every file in `extras`.
- They open the cited edges.
- Each judge asks the system one real question of their own.

Unknown: how the 40 points split across the criteria, and who the judges are.

## Checklist

### 1. Method and fit
- [x] **README "How it works" explains the 4 steps.** A fresh-clone reader followed it. Jargon (CAMO, ECE, D1–D6) is tracked in #118.
- [ ] **README says *why* this design suits the task.** #117
- [ ] **README says which question shapes work.** #117, #114
- [x] **README Results table reproduces at HEAD.** `eval` at `d25703c`: class 0.6867 / ECE 0.0867, node 0.6304 / ECE 0.0304, 0 calls, which matches exactly. Only the commit label is stale (#117).

### 2. Faithfulness
- [x] **Associational evidence never gets a causal verb; a null is never read as a decrease.** 12 of 12 sampled class-dev answers pass, including 3 associational-only answers and 2 nulls.
- [x] **Evidence pages match `answers.json`.** For the 12 sampled answers, each page has the same text, every cited edge id, and each verbatim `original_sentence` with its title, year and DOI. Votes, the sign trace and excluded edges are shown.
- [ ] **Cited edges bear on the question and support the headline.** In 4 of 12 sampled answers, off-topic or stand-in edges flip the verdict: #116. The b4 sign is tracked in #101, and class mislinks (c4, C-C0052) in #88.
- [ ] **Every study named in the text has a cited edge.** #100 (the 25-edge cap). Herbicide questions cite 4–7 of the 10 studies they name.
- [ ] **Answer text reads cleanly.** Problems: pasted question spans, "higher which species…", author casing such as "McLACHLAN". Tracked in #113 and #101.

### 3. Honest limits
- [x] **`limits.html` shows failures with concrete examples.** It covers each trap tag with counts, the first 3 misses unfiltered, correct answer vs ours, a reliability table, the ECE miss and the non-goals. It says it measures an older commit.
- [ ] **Shipped confidence is disclosed.** Every answer carries a constant 0.6, and neither the README nor `limits.html` says so plainly. #117
- [ ] **no_evidence separates "graph has nothing" from "couldn't read the question" consistently.** #103 (`answer` and `searched_for` disagree on parse failures).
- [ ] **Non-goals and the limits page are reachable from the README.** #117

### 4. Value to a real user
- [ ] **A judge's own free-form question works with the LLM set.** 15 questions were asked through `./ask.sh` with the live endpoint:
  - 13 linked, each in 0.2–6.8 s;
  - how-to and narrative questions fail ("How do I control garlic mustard?"): #114;
  - 3 of the 13 linked answers have wording problems (#113);
  - 1 of the 13 has an off-topic headline (#116).
- [ ] **The refusal tells the user what to do next.** The wording "(nothing) -> nothing" is tracked in #114.
- [x] **Evidence pages give what a practitioner needs:** direction, certainty and confidence kept separate, per-study votes, quotes and DOIs. Literal `<i>` tags in titles are #107.
- [x] **The gap map reads without explanation.** The legend and shading bands are stated, "gap" is printed in empty cells, and the densest list and empty causes are shown (screenshot review). An ecologist's read is still open in #109.
- [ ] **Example outputs are visible without running.** `outputs/` is gitignored: #117

### 5. Craft and reuse
- [x] **`./run.sh` from a fresh clone without mise or uv:** 3.1 s, `.venv` created, valid output, 0 calls.
- [x] **"Extend it in 10 minutes" works as written.** A fresh clone took about 2.5 min, contract tests passed, and `eval` ran. The full suite gave 524 passed, 5 xfailed. Snags (venv activation, no eval headline) are in #118.
- [x] **LICENSE present:** MIT.
- [ ] **Documented programmatic use, an `experiments/` index, and an explained root layout.** #118. Gitignore hygiene is #105.

### 6. Accessibility
- [x] **Static WCAG audit:** `scripts/a11y_audit.py outputs` gives 0 findings over 14 pages. axe-core (0 violations) is recorded in ROADMAP item 19.
- [x] **Reflow at 320 px:** headless Firefox screenshots of the index, b4, gap map and limits pages show no page-level horizontal scroll. Only tables scroll, inside their region.
- [ ] **Real keyboard, screen reader, light/dark toggle and 200% zoom by a human.** Only the dark scheme was screenshotted, and the markup was reviewed. #108, #109

## Human-check issues (#108–#112): what is already covered

- **#108:** the b4 known problems and the 320 px reflow are covered above. Left for a human: OS light/dark toggle, keyboard focus, 200% zoom, DOI clicks.
- **#109:** shading and legend, the limits page's honesty and the older-commit note are covered above. Left for a human: clicking cells into `gapcells.html`, dark/light, keyboard.
- **#110:** faithfulness was sampled on 12 class-dev answers (above). Left for a human: the 10 practice answers (9 are no_evidence) and a judgement call on wording.
- **#111:** live `ask` with the real endpoint was covered by 15 questions (above). Left for a human: bad-key and down-endpoint behaviour, scheme-less URL (#102), and the batch pages staying unchanged after `ask`.
- **#112:** not covered (GitHub render and the final tag).
