# Design rules (binding)

From the redesign brief (`docs/superpowers/specs/2026-08-22-ui-redesign-brief.md`).
These exist because every screen here will be rendered twice — React on the web
and React Native on the phone — and each rule below is a pattern that survives
both. CI enforces what it can; the rest is review.

## Enforced by CI (`tests/test_design_system.py`)

- **No hex color literal outside the token files.** Every color lives in
  `tokens.json` and reaches code only through `tokens.css` / `tokens.ts`.
  The dual palette dies from one stray hex, and that is a CI problem, not a
  discipline problem.
- **No `<table>`.** Tables do not exist in React Native. Lists are flex rows.
- **No `position: sticky`.** Pin things by making them siblings of the scroll
  area (header / scrolling body / footer in a flex column), which is also the
  only pattern RN can express.

## Enforced by review

- **No hover-only affordances.** Hover may enhance; it may never be the only
  way to discover or reach something.
- **No dark-theme shadows.** Elevation is 1px borders and fill steps; the one
  shadow (`--shadow-sheet`) is reserved for sheets and modals.
- **Type floor 12px. Touch floor 44px** (48px for the study rating row).
- **Fonts:** Inter via Google Fonts on web with the `system-ui` fallback stack.
  If Inter's tabular numerals fail verification on Hermes later, the RN theme
  drops to the system stack rather than shipping proportional stats.
- **Browser-only primitives live behind seams:** auth in `session.js`, file
  intake behind `upload()`, persistence behind the storage adapter in
  `queue.js`, ids behind `uuid()`. RN fills the seams; screens never notice.
- **Copy:** decayed retrievability is "due for review", never "forgotten";
  streak-at-risk is status, never guilt; the words "runs" and "tab" never ship;
  no mascots, badges, XP, confetti, or congratulatory prose longer than a line.
