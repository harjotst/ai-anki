# 13 — Deck lineage & Card Ledger

**What to build:** A deck becomes a living thing that outlives the job that made it. This ticket delivers safe add-only regeneration: new material adds new cards and existing cards are left completely untouched, so review history, hand edits and tags all survive by construction. It also resolves the retention contradiction — sources are purged, the ledger never is.

**Blocked by:** 10 — Deck sophistication; 05 — Job state machine

**Status:** done — 8 tests; add-only regeneration proven non-destructive in a real Anki collection

- [x] A Deck entity exists distinct from Job, and a Job runs against a Deck
- [x] The Card Ledger stores identifier, deck path, note type, question fingerprint and last-exported field text
- [x] Deck path is frozen per card at first export and reused on every later export, because Anki never moves an existing card
- [x] Note type is pinned per card
- [x] Cards whose field text is unchanged are omitted from the package entirely, so anything the user changed in Anki survives
- [x] Regeneration defaults to add-only, leaving existing cards untouched
- [x] Scheduled purging removes uploaded sources and generated packages but never touches the ledger
- [x] The database is backed up off-platform on a schedule, since platform snapshots are documented as not being a backup
- [x] The Anki contract harness asserts an add-only regeneration leaves existing notes, their tags and their scheduling unchanged

**Carried finding (from ticket 02):** Anki's default import setting is *update if newer*,
compared against each note's modification time. genanki stamps that from the export
timestamp. An export stamped at or before the previous one is filed as a **duplicate** and
silently changes nothing — no error, and our app would report success. Every regeneration
must stamp a strictly later timestamp than the export it supersedes, and that needs its own
assertion. `build_package(..., timestamp=)` exists for this; the download path must pass it
rather than relying on `time.time()`.
