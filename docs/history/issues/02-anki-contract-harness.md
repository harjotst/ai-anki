# 02 — Anki contract harness

**What to build:** The second test seam. A test-only harness imports a generated `.apkg` into a real temporary Anki collection and asserts what only Anki can report. Every later ticket leans on this: the identity constraints in the spec were discovered here rather than reasoned about, and without it those failures are invisible until they reach a user's collection.

**Blocked by:** 01 — Walking skeleton

**Status:** done — 9 contract tests green against real Anki 26.08.1

> Found while building this: an export whose note timestamp does not advance past the
> previous export is filed by Anki as a **duplicate** and silently changes nothing.
> `build_package` now takes an explicit `timestamp`. See tickets 13 and 14.

- [x] The official `anki` package is a dev/test dependency only, never imported by application code, with a test asserting that
- [x] A helper creates a temporary collection, imports a given package, and exposes the resulting decks, notes and cards
- [x] Asserts a `::` deck name produces the nested hierarchy, with intermediate parent decks auto-created by Anki
- [x] Asserts a note re-imported under the same GUID updates in place rather than duplicating
- [x] Asserts a note re-imported with a changed note type is reported as conflicting and does not update
- [x] Asserts a cloze note produces one card per distinct cloze ordinal
- [x] Asserts a cloze-typed note with no cloze marker produces zero cards, documenting the genanki defect we work around
- [x] The Anki version under test is pinned and recorded
