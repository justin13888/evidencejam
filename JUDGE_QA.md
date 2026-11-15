# Judge QA: the 40 judged points

The 40 points are judged subjectively. This file maps them to the repo and records what has already been checked, so nobody re-checks it. Each item is ticked only when it is basically complete. Open items name the issue that tracks the gap.

**Verified at:** master `6764660`, Sun 2026-11-15, 15:44 EST (first pass at `d25703c`). Default strategies: `parser/freeform`, `linker/cessation`, `citer/precise`, `calibrator/baseline`, `renderer/faithful`, `extras/gapmap`. `ask.sh` adds `parser/assisted` and `linker/assisted`.
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
- [x] **README says *why* this design suits the task.** It's the "Why this design" section (#117).
- [x] **README says which question shapes work.** It's the "What it can and can't answer" section (#117).
- [x] **README Results table reproduces at HEAD.** `eval` at `6764660`: class 0.6867 / ECE 0.0867, node 0.6304 / ECE 0.0304, 0 calls. Cited-edge precision and recall were updated for the `precise` citer: class 0.48 / 0.59, node 0.44 / 0.57.

### 2. Faithfulness
- [x] **Associational evidence never gets a causal verb; a null is never read as a decrease.** 12 of 12 sampled class-dev answers pass, including 3 associational-only answers and 2 nulls.
- [x] **Evidence pages match `answers.json`.** For the 12 sampled answers, each page has the same text, every cited edge id, and each verbatim `original_sentence` with its title, year and DOI. Votes, the sign trace and excluded edges are shown.
- [ ] **Cited edges bear on the question and support the headline.** In 4 of 12 sampled answers, off-topic or stand-in edges flip the verdict. Deferred by the owner: #116 and #101 are labelled `not-planned-for-now`. Class mislinks (c4, C-C0052) are in #88.
- [x] **Every study named in the text has a cited edge.** Fixed in #100. `experiments/renderer/consistency_check.py` now asserts it: 29 violations before, 0 after.
- [x] **Answer text reads cleanly.** Fixed in #113:
  - no pasted question text;
  - correct subject–verb agreement;
  - composition outcomes read "a change in";
  - surnames are normalised;
  - LLM-linked answers name the linked classes, so "dogwood" is never claimed from general native-species evidence.

  The b4 sign is still wrong (#101, deferred).

### 3. Honest limits
- [x] **`limits.html` shows failures with concrete examples.** It covers each trap tag with counts, the first 3 misses unfiltered, correct answer vs ours, a reliability table, the ECE miss and the non-goals. It says it measures an older commit.
- [x] **Shipped confidence is disclosed.** The README and the top of `limits.html` both say every answer carries 0.6 (#117).
- [x] **no_evidence separates "graph has nothing" from "couldn't read the question" consistently.** `answer` and `searched_for` give one reason (#103).
- [x] **Non-goals and the limits page are reachable from the README.** (#117)

### 4. Value to a real user
- [x] **A judge's own free-form question works with the LLM set.** The same 15 questions were re-run after #113 and #114:
  - all 15 get an answer, a no-evidence reply or a helpful redirect;
  - "How do I control garlic mustard?" lists the interventions with evidence;
  - the dogwood story question is answered in class terms.

  Remaining: "drought → tree growth" is still wrong (#116, deferred). Shared-endpoint latency occasionally exceeded the old 3 s timeout, so `ask.sh` now waits 8 s.
- [x] **The refusal tells the user what to do next.** It names what it couldn't find, the nearest classes and an example question (#114).
- [x] **Evidence pages give what a practitioner needs:** direction, certainty and confidence kept separate, per-study votes, quotes and DOIs. `<i>` in titles now renders as emphasis (#107). The pages were restyled with a modern type scale and palette in both schemes.
- [x] **The gap map reads without explanation.** The legend and shading bands are stated, "gap" is printed in empty cells, and the densest list and empty causes are shown (screenshot review). An ecologist's read is still open in #109.
- [x] **Example outputs are visible without running.** README screenshots are in `docs/img/` (#117).

### 5. Craft and reuse
- [x] **`./run.sh` from a fresh clone without mise or uv:** 3.1 s, `.venv` created, valid output, 0 calls.
- [x] **"Extend it in 10 minutes" works as written.** A fresh clone took about 2.5 min, contract tests passed, and `eval` ran. The full suite gave 524 passed, 5 xfailed. Snags (venv activation, no eval headline) are in #118.
- [x] **LICENSE present:** MIT.
- [x] **Documented programmatic use, an `experiments/` index, and an explained root layout.** (#118). Gitignore hygiene is still open in #105.

### 6. Accessibility
- [x] **Static WCAG audit:** `scripts/a11y_audit.py outputs` gives 0 findings over 14 pages after the restyle. axe-core (0 violations) is recorded in ROADMAP item 19 for the pre-restyle CSS.
- [x] **Reflow at 320 px:** headless Firefox screenshots of the index, b4, gap map and limits pages show no page-level horizontal scroll. Only tables scroll, inside their region.
- [ ] **Real keyboard, screen reader, light/dark toggle and 200% zoom by a human.** Only the dark scheme was screenshotted, and the markup was reviewed. #108, #109

## Human-check issues (#108–#112): what is already covered

- **#108:** the b4 known problems and the 320 px reflow are covered above. Left for a human: OS light/dark toggle, keyboard focus, 200% zoom, DOI clicks.
- **#109:** shading and legend, the limits page's honesty and the older-commit note are covered above. Left for a human: clicking cells into `gapcells.html`, dark/light, keyboard.
- **#110:** faithfulness was sampled on 12 class-dev answers (above). Left for a human: the 10 practice answers (9 are no_evidence) and a judgement call on wording.
- **#111:** live `ask` with the real endpoint was covered by 15 questions (above). Left for a human: bad-key and down-endpoint behaviour, scheme-less URL (#102), and the batch pages staying unchanged after `ask`.
- **#112:** not covered (GitHub render and the final tag).
