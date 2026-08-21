# 01 — Walking skeleton

**What to build:** A user uploads a single `.txt` file and downloads an `.apkg` built from it. This is the tracer bullet: it cuts through upload, the Deck Plan pass, the card pass, package generation, persistence, and a minimal React shell. Deliberately shallow — one flat deck, Basic notes only, no auth, no durability guarantees. Its job is to prove the whole chain exists and that Anki actually accepts what we produce.

**Blocked by:** None — can start immediately

**Status:** acceptance criteria met — frontend shell still outstanding (see note)

> Note: all 8 acceptance criteria pass (13 tests green, plus a real-Anki import check).
> The "minimal React shell" named in *What to build* is NOT built — the app is API-only.
> Nothing is committed yet.

- [x] Uploading a `.txt` returns a job identifier and eventually a downloadable `.apkg`
- [x] Pass 1 returns a Deck Plan via validated structured output, modelled as a flat topic array carrying a `::` path string — a recursive schema is never sent, because structured outputs reject them
- [x] Pass 2 runs once per topic and returns cards via validated structured output
- [x] Every Anthropic response checks `stop_reason` before reading content; a refusal surfaces as a job error rather than an exception
- [x] The generated `.apkg` imports into Anki with no error and the cards are reviewable
- [x] genanki model identifiers are hardcoded module constants, never randomised per job
- [x] Job and card rows persist in SQLite
- [x] Tests drive the flow through the HTTP boundary with only the Anthropic network transport faked, via an httpx mock transport; no test-only abstraction is introduced into application code
