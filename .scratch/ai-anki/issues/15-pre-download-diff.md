# 15 — Pre-download diff

**What to build:** Before an update lands, the user sees exactly what it will do and can veto any part of it. Updating stays opt-in; the safe path remains the default.

**Blocked by:** 14 — Slot matching

**Status:** done — 6 tests; add-only is the default, skips are honoured by omission

- [x] Before download the user sees counts of notes to be updated, added and left untouched
- [x] Notes to be updated are listed with their existing and proposed text
- [x] Individual updates can be skipped and are then omitted from the package entirely
- [x] Updating remains an explicit opt-in, with add-only as the default
- [x] The page states that hand-added tags on updated notes are replaced, and suggests flags as the durable alternative
