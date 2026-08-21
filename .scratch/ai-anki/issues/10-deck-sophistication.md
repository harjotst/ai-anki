# 10 — Deck sophistication

**What to build:** The deck stops being flat. Hierarchy, mixed note types, and tags — the levers that make a complicated document produce a complicated deck. Every claim here is asserted against a real collection rather than against our own code.

**Blocked by:** 02 — Anki contract harness; 01 — Walking skeleton

**Status:** done — 6 tests, hierarchy/note-types/cloze-counts/tags all asserted in a real Anki collection

- [x] Topics map to `::` deck paths and produce nested subdecks; only leaf decks are emitted, since intermediate parents are created by Anki
- [x] Cards select between Basic and Cloze per card
- [x] Cloze text is validated for a marker before the note is constructed; failures downgrade to Basic and are recorded, because the packaging library silently emits zero cards otherwise
- [x] Model identifiers and their field and template lists are frozen constants, with a test asserting they have not changed
- [x] Cards carry topic, difficulty, source page and job tags
- [x] Difficulty influences question style, not merely card count
- [x] The Anki contract harness asserts hierarchy, per-card note types, cloze card counts and tags in a real collection
