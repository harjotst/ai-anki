# 14 — Slot matching

**What to build:** In-place updating: the headline feature. A regenerated card must be matched to the card it replaces, and the matching must be validated rather than assumed. Positional matching is forbidden — it silently attaches a long review interval to a question the user has never seen, which corrupts rather than clutters and is therefore worse than duplicating.

**Blocked by:** 13 — Deck lineage and Card Ledger

**Status:** done — 9 tests; claims are declared by the model then verified server-side

> The similarity threshold is `ledger.MATCH_THRESHOLD = 0.55`, with tests either side of it.
> It is the riskiest tunable here and wants calibrating against real material before launch.
> An *exact* normalised-question match still adopts identity without a claim — that needs no
> judgement, and it is what keeps ticket 13's add-only guarantee intact.

- [x] Card identity is deck, topic path and slot index, persisted in the ledger
- [x] The generation pass receives existing cards for its topic after the cache breakpoint and returns, per card, either the identifier it is revising or an explicit new marker
- [x] The server rejects a claimed reuse whose similarity to the stored fingerprint falls below threshold
- [x] A claimed identifier that does not belong to that topic is rejected
- [x] Unclaimed cards are retired, and retired identifiers are never reissued
- [x] A note type change retires the old identifier and mints a new one rather than reusing the GUID, since Anki silently skips notes whose note type changed
- [x] Positional matching is not used anywhere
- [x] A test regenerates a deck twice and asserts identifier stability for unchanged slots
- [x] The Anki contract harness asserts an in-place update preserves scheduling on the updated note

**Carried finding (from ticket 02):** Anki's default import setting is *update if newer*,
compared against each note's modification time. genanki stamps that from the export
timestamp. An export stamped at or before the previous one is filed as a **duplicate** and
silently changes nothing — no error, and our app would report success. Every regeneration
must stamp a strictly later timestamp than the export it supersedes, and that needs its own
assertion. `build_package(..., timestamp=)` exists for this; the download path must pass it
rather than relying on `time.time()`.
