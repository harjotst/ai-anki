# Spec — ai-anki

Turn study documents into Anki decks whose structure and difficulty scale with the material.

**Status:** ready-for-agent
**Verified:** claims marked ✅ below were checked against primary sources (library source, Anki's Rust source, Anthropic docs) and against a live Anki 26.08 collection. See `docs/verification.md`.

---

## Glossary

Use this vocabulary throughout the codebase and tickets.

| Term | Meaning |
|---|---|
| **Deck** | A long-lived lineage that a user builds up over time. Owns the Card Ledger. Survives regeneration. Not the same as an Anki deck. |
| **Job** | One run against a Deck: upload → convert → plan → generate → assemble. A Deck has many Jobs over its life. |
| **Source** | One uploaded file belonging to a Job. |
| **Deck Plan** | Pass 1's output: a flat list of Topics with difficulty, claim assignments, and proposed card counts. Editable by the user before generation. |
| **Topic** | One node of the Deck Plan. Carries a `deck_path`, a difficulty, a note type, and an exclusive list of Claims. |
| **Claim** | A specific fact or point assigned to exactly one Topic. Claims partition the material so parallel Topic calls don't duplicate each other. |
| **Card** | A generated question/answer pair. Has a stable UUID used as the Anki note GUID. |
| **Slot** | The identity of a Card across regenerations: `(deck_id, topic_path, slot_index)`. Pass 2 declares which Slot each generated card revises. |
| **Card Ledger** | The permanently-retained table of Cards: UUID, deck path, note type, question fingerprint, last-exported field text. Never purged. |
| **Retired** | A Card the model stopped producing. Its UUID is reserved forever and never reissued. |
| **Deck Path** | The `::`-separated Anki deck name a Card was first exported under. Frozen per Card at first export. |
| **Invite Token** | A per-person signed credential granting access and carrying an attributable spend budget. |

---

## Problem Statement

Making good Anki cards from lecture material is slow, and it is the step where most people give up. A student finishes a lecture with a PDF of slides, a chapter of a textbook, and their own notes, and faces an hour of manual transcription before a single review happens. The tedium is worst exactly when the material is densest — which is when good cards matter most.

Tools that automate this generally fail in one of two ways. They produce a flat pile of shallow recall cards regardless of what the source actually contains, so a dense pharmacology chapter and a padded syllabus yield the same thing. Or they produce a one-shot artifact you cannot iterate on: when the lecturer posts a corrected slide deck in week 6, the only options are to hand-patch or to re-import and duplicate everything, losing weeks of review scheduling.

Users also cannot see or steer the tradeoff. They cannot tell in advance how many cards a document will produce, what it will cost, or whether the tool understood the structure of their material — they find out only after the work and the money are spent.

## Solution

A web app where a user uploads the documents for a unit of study and gets back an `.apkg` file whose deck hierarchy, note types, and question difficulty reflect the material they actually uploaded.

The generation is deliberately interrupted twice so the user stays in control of both cost and quality:

1. **Plan checkpoint.** A first Claude pass reads everything and proposes a Deck Plan — topics, difficulty, the specific claims each topic owns, and how many cards each warrants. The user sees this, edits it, and sees a real token count and dollar estimate before approving anything expensive.
2. **Card checkpoint.** A second pass generates cards per topic in parallel. The user reviews them in a table, edits wording, deletes duds, re-rolls individual cards, and regenerates whole topics before anything is packaged.

Because the app keeps a permanent Card Ledger, a Deck is a living thing rather than a one-shot export. When week 6's corrected slides arrive, the user adds them to the same Deck and regenerates: Claude declares which existing cards it is revising, the server validates those claims, and the resulting `.apkg` updates exactly those notes in place — preserving every card's review scheduling — while adding genuinely new ones and leaving everything else untouched.

## User Stories

**Access and cost**

1. As an invited user, I want to open the app with a personal invite link, so that I can use it without the owner sharing one password with everyone.
2. As the owner, I want to revoke one person's invite token without logging everyone else out, so that a leaked link is a small problem rather than a rotation.
3. As the owner, I want to see how much each person's jobs have cost, so that I can tell who is driving the bill.
4. As the owner, I want a hard monthly spend cap that the application cannot exceed even if it has a bug, so that a runaway loop cannot produce a four-figure invoice.
5. As a user, I want to see the measured token count and estimated cost of my job before I approve generation, so that I am never surprised by what I spent.
6. As a user, I want the app to refuse a job that is too large rather than failing partway through, so that I do not pay for ingestion that could never have completed.
7. As the owner, I want a kill switch that stops all generation immediately, so that I can halt spending without redeploying.

**Uploading and ingestion**

8. As a user, I want to upload PDF, DOCX, PPTX, XLSX, plain text, Markdown, and image files, so that I can use whatever my lecturer actually published.
9. As a user, I want to upload several files into one job, so that slides, textbook chapter, and my own notes become one coherent deck instead of three disconnected ones.
10. As a user, I want to upload files one at a time with visible per-file progress, so that a failure on file 6 does not lose files 1 through 5.
11. As a user, I want scanned or photographed pages to work, so that a photocopied chapter is as usable as a born-digital one.
12. As a user, I want a photo of my handwritten notes to be accepted, so that I can include material that only exists on paper.
13. As a user, I want spreadsheets to be read as tables rather than as pictures of tables, so that the data is understood and I am not billed for rendering it.
14. As a user, I want a clear message naming the specific file when a conversion fails, so that I can remove or replace just that one.
15. As a user, I want to paste raw text instead of uploading, so that I have a fallback when a file will not process.

**Planning**

16. As a user, I want to see a proposed topic breakdown before any cards are generated, so that I can tell whether the tool understood my material.
17. As a user, I want each topic to show a difficulty rating and the reasoning behind it, so that I can judge whether the assessment is sensible.
18. As a user, I want to see how many cards each topic proposes, so that I can spot a topic that is about to be over- or under-covered.
19. As a user, I want to change a topic's proposed card count, so that I can go deeper on the material I find hard.
20. As a user, I want to delete a topic entirely, so that I do not get cards for the administrative slides at the front of the deck.
21. As a user, I want to rename a topic and change where it sits in the hierarchy, so that the deck matches how I think about the subject.
22. As a user regenerating an existing Deck, I want topics whose cards were already exported to be visibly locked against reparenting, so that I am not promised a reorganisation Anki will not perform.
23. As a user, I want to change a topic's note type before its first generation, so that I can force cloze on material I know suits it.
24. As a user, I want to see which specific claims each topic owns, so that I can tell whether the material has been divided sensibly.
25. As a user, I want to save a plan and come back to it later, so that I do not lose work if I close the tab.

**Generation**

26. As a user, I want cards to appear topic by topic as they finish, so that I can start reading them without waiting for the whole job.
27. As a user, I want to see which topic is currently generating and how many remain, so that a four-minute wait feels finite.
28. As a user, I want to close the tab and return to a URL later, so that I am not chained to the browser.
29. As a user, I want a job interrupted by a server restart to resume rather than silently die, so that I do not lose work I have paid for.
30. As a user, I want a job that fails on one topic to let me retry just that topic, so that one failure does not re-bill me for fourteen successes.
31. As a user, I want dense conceptual material to produce application and comparison questions, not just definitions, so that the cards test understanding.
32. As a user, I want simple factual material to produce simple recall cards, so that the tool does not manufacture false depth.
33. As a user, I want sequences, processes, and lists to become cloze deletions, so that the card format matches the content.
34. As a user, I want cards tagged with their topic, difficulty, and source page, so that I can search and filter inside Anki.
35. As a user, I want every card tagged with its job, so that I can find and mass-delete one bad batch in Anki with a single search.

**Reviewing cards**

36. As a user, I want to see every generated card before it reaches my collection, so that nothing I have not read enters my reviews.
37. As a user, I want cloze cards rendered as they will appear rather than as raw markup, so that I can judge them properly.
38. As a user, I want to edit a card's text inline, so that I can fix an awkward phrasing without regenerating.
39. As a user, I want to delete individual cards, so that I can drop the ones that are not worth reviewing.
40. As a user, I want to re-roll a single card, so that I can ask for a second attempt at a badly-worded one.
41. As a user, I want to regenerate an entire topic, so that I can fix a section that came out uniformly poor.
42. As a user, I want to reject all cards in a topic at once, so that I am not clicking delete forty times.
43. As a user, I want near-duplicate cards flagged and grouped, so that I do not end up reviewing the same fact in three subdecks forever.
44. As a user, I want to see which topic each card came from while reviewing, so that I have the context to judge it.

**Export and import**

45. As a user, I want to download a single `.apkg` file, so that importing is one double-click.
46. As a user, I want the deck hierarchy preserved as Anki subdecks, so that I can study one topic at a time.
47. As a user, I want to be told to leave Anki's import defaults alone, so that I do not break update-in-place by changing a setting I did not understand.
48. As a user, I want the job's tag search string shown on the download page, so that I can undo a bad import.
49. As a user, I want images referenced by cards bundled into the file, so that nothing renders as a broken link.

**Regeneration**

50. As a returning user, I want to add new source material to an existing Deck, so that I can build one deck across a whole semester.
51. As a returning user, I want cards whose content did not change to be omitted from the file entirely, so that my own Anki edits, hand tags, and leech flags survive.
52. As a returning user, I want a diff before download telling me how many notes will be updated, added, and left alone, so that I know what I am about to do.
53. As a returning user, I want to see exactly which notes will be updated and skip any of them individually, so that I can protect a card I have hand-corrected.
54. As a returning user, I want updated cards to keep their review scheduling, so that six weeks of progress survives a correction.
55. As a returning user, I want "add new cards only" to be the default and updating to be an explicit opt-in, so that the safe path is the one I get by accident.
56. As a returning user, I want a card the model stopped producing to be left alone in my collection rather than deleted, so that the tool never destroys work without asking.
57. As a returning user, I want a card whose note type would have to change to be added as a new card rather than silently failing, so that the import does not quietly do nothing.
58. As a returning user, I want my Deck's card history retained indefinitely, so that regenerating after a long gap does not duplicate everything.

**Operations**

59. As the owner, I want uploaded source files purged on a schedule, so that I am not indefinitely hosting other people's copyrighted textbooks.
60. As the owner, I want the Card Ledger exempt from purging, so that retention policy does not destroy the update feature.
61. As the owner, I want the database backed up off-platform, so that losing the volume does not orphan every user's review history.
62. As the owner, I want per-call token usage persisted, so that cost is auditable after the fact rather than estimated.
63. As the owner, I want a job that crash-loops to stop retrying and require manual intervention, so that a deterministic bug cannot re-bill the cache write indefinitely.

---

## Implementation Decisions

### Architecture

- Single container. FastAPI serves both the JSON API and the built React/Vite static assets. No second service, no separate worker process, no Redis.
- Python 3.12 pinned in the image. The developer's local 3.14 is ahead of the dependency set.
- SQLite on a mounted volume is the only datastore. In-process background worker. Deployed to Fly.io.
- Hosting requires ≥1GB memory: LibreOffice peaks at ~218MB RSS per conversion ✅, so a 256MB machine OOMs on a single file.

### Ingestion

- **One internal format: PDF.** DOCX and PPTX convert via headless LibreOffice; PDFs and images pass through natively; XLSX extracts to Markdown tables via openpyxl; text and Markdown pass through as strings.
- **LibreOffice gets a fresh `-env:UserInstallation` temp profile per invocation.** ✅ Sharing a profile does not serialise, it *fails silently* — six concurrent conversions produced two PDFs and four bare exit-1s with no error output at all. A missing profile dir fails loudly with exit code 77, so no hang detection is needed for that case; keep a subprocess timeout for other reasons.
- LibreOffice concurrency is bounded by a semaphore sized to available vCPUs. This is unrelated to the Claude fan-out limit and must not be conflated with it — on 1 vCPU, concurrency is exactly linear and buys nothing.
- Assembled documents are uploaded to the Anthropic Files API and referenced by `file_id`. This is the only way past the 32MB request limit ✅ — but it does **not** raise the page limit or the context window, and must not be treated as if it does.

### Admission control

- **The job size gate is `count_tokens()` over the exact assembled request, run after conversion and before pass 1.** Page count is rejected as the unit: DOCX has no page count until laid out, images and XLSX have none at all, and a PDF page costs 1,500–3,000 text tokens *plus* up to 4,784 visual tokens ✅ because every page is billed as text and image both.
- Reject above ~700k input tokens, leaving headroom inside the 1M context for `max_tokens`. The user-facing contract is the measured token count and dollar estimate, never a page number.
- A cheap page-count pre-filter may run after conversion to reject the obviously-oversized before paying for a Files API upload.

### Model usage

- `claude-opus-5` for both passes. Adaptive thinking on. Effort `high` on pass 1, `medium` on pass 2.
- `max_tokens` caps thinking *and* response text together ✅ — budget for both or responses truncate mid-card.
- **Every response checks `stop_reason` before reading `content`.** Opus 5 safety classifiers return refusals as HTTP 200, so indexing `content[0]` blind crashes on refusal.

### Prompt caching

The cost model depends entirely on this layout, which is mandatory and identical across both passes:

1. Tools: identical or absent.
2. System: **one generic, pass-agnostic prompt, byte-identical across passes.**
3. First user content block: the document(s), with `cache_control` `{type: ephemeral, ttl: 1h}` on the last document block.
4. *After* the breakpoint, in the same user message: the pass-specific instruction.

The pass-specific instruction must **never** go in `system`. Render order is tools → system → messages ✅, so a differing system tier makes the document tier unmatched and every pass-2 call pays full price.

**Pass 2 fans out only after pass 1 has completed.** ✅ A cache entry becomes readable only once the first response begins; N concurrent requests on a cold prefix all miss, and each independently pays a 2× cache-creation charge — worse than not caching. The two-pass shape with a human approval step in the middle satisfies this naturally and needs no pre-warm call.

### Deck Plan (pass 1)

- The plan is a **flat array of topics**, each carrying a `::`-separated `path` string. It is explicitly **not** a recursive tree — structured outputs reject recursive schemas outright ✅. Shape, trimmed to the decision-bearing parts:

```
topics: [ {
  topic_id, path, difficulty (enum), rationale,
  note_type (enum), proposed_card_count,
  claims: [ string ],        // exclusive to this topic
  source_pages: [ integer ]
} ]
```

- **Pass 1 partitions the material, not just names it.** Each topic owns an exclusive list of claims. Pass 2 for a topic is instructed to cover only its own claims and is given sibling topic titles as explicit exclusions. Without this, parallel topic calls each see the whole corpus and independently generate the same card.
- Numeric bounds (`minimum`, `maximum`, `maxItems`) are unsupported ✅ and must be validated in Python after parsing; put the intent in field descriptions. Enum values are compared case-insensitively — capitalization is not guaranteed.
- `source_page` is self-reported by the model. The citations API cannot be used: **citations and structured outputs are mutually exclusive and return a 400** ✅, and scanned PDFs are uncitable regardless.

### Card identity and regeneration

This is the core of the data model, not a detail.

- A **Deck** is a persistent lineage distinct from a Job. Regeneration is "a new Job against Deck D", never a fresh Deck.
- Card identity is the **Slot**: `(deck_id, topic_path, slot_index)`. Each Card holds a UUID used directly as the genanki note GUID ✅ (`Note(guid=...)` pins it permanently; the default is a content hash and would defeat the whole feature).
- On regeneration, pass 2 receives the existing cards for its topic — UUID and question text, placed **after** the cache breakpoint — and must return per card either the `existing_card_id` it is revising or `"new"`.
- **The server validates every claimed reuse** against the stored question fingerprint and rejects claims below a similarity threshold. Positional matching is forbidden: it silently attaches a user's 90-day review interval to a question they have never seen, which is worse than duplicating because it corrupts rather than clutters.
- Cards the model does not claim are **retired**. Their UUID is reserved permanently and never reissued. Retired cards are not deleted from the user's collection.
- **Note type is pinned per UUID.** ✅ Anki's importer skips a note whose `notetype_id` differs from the existing one — logged as conflicting, not updated, junk notetype left behind — and if the user has ever enabled "Merge note types" (sticky once set) the *entire import aborts*. A genuine Basic↔Cloze change retires the old UUID and mints a new one.
- **Deck path is frozen per UUID at first export.** ✅ Anki matches decks by name and never rewrites an existing card's deck, so a reorganised plan would update text while leaving cards behind and littering the collection with empty decks. Mutable topic identity lives in tags, which *are* replaced on update. The plan editor locks already-exported paths and explains why.
- **Only changed cards are exported.** Last-exported field text is stored per UUID; byte-identical output is omitted from the package entirely, so the user's Anki edits, hand tags, leech and marked flags survive untouched. "Add new cards only" is the default; updating is an explicit opt-in behind a diff screen.

### Anki package generation

- `genanki`, pinned exactly. MIT-licensed and adequate; last release 2023-11-12 and last commit 2024-12-30, but verified to import cleanly into Anki 26.08 ✅. The used surface is small enough to fork if it dies.
- **The official `anki` PyPI package is rejected for runtime use: it is AGPL-3.0-or-later** ✅, and a publicly-reachable service triggers the network-copyleft obligation. It is adopted as a **dev-only test dependency**, never imported by the server.
- **Model IDs are hardcoded app-wide constants**, never randomised per job as genanki's README suggests ✅ — a changing model id is itself the notetype-conflict trigger. Field and template lists are frozen; changing them requires allocating a new model id.
- **Cloze text is validated server-side before constructing a Note.** ✅ genanki 0.13.1 contains a live bug — `if card_ords == {}` compares a set against a dict and is always False — so a cloze note with no `{{cN::}}` marker yields **zero cards, silently, with the note still present in the collection**. Fixed upstream, never released. Cards failing marker validation are downgraded to Basic.
- Only leaf decks are emitted. Anki auto-creates intermediate parents ✅; `::` handling is entirely Anki-side and absent from genanki.
- Media files are bundled via the package's media list; fields reference them by basename.
- A cross-topic dedup step runs before packaging: exact normalised front matching, plus one Claude call grouping semantic duplicates. Collapsed duplicates are surfaced in the review screen, never deleted silently.

### Jobs, durability, and failure

- Explicit job state machine: `uploaded → converting → planning → plan_ready → generating → reviewing → assembling → complete`, plus `failed`, `interrupted`, `dead`, `cancelled`.
- Pass 2 is one row per `(job_id, topic_id)` with its own status, attempt count, and persisted card payload. Retry selects only failed rows. Each topic's result is written in a transaction that first deletes any prior attempt's cards, so retries replace rather than accumulate.
- **Jobs must be crash-safe, not merely autostop-safe.** ✅ Deploys, `fly secrets set`, scale changes, host migrations and OOM all SIGTERM the machine; `kill_timeout` maxes at 300s and is documented as best-effort. Boot scans for non-terminal jobs with no live worker and resumes or marks them `interrupted`.
- `attempt_count` increments in a committed transaction **before** the first Anthropic call of a resume, not after success. At 3 attempts the job moves to `dead` and requires manual clearing. Minimum 60s backoff between resumes. Without this, a deterministic crash re-pays the cache write — roughly $7 per cycle on a large document — several times a minute.
- Exec-form `CMD` so the app is PID 1 and receives SIGTERM; an asyncio handler drains with an internal deadline below `kill_timeout`.

### Progress reporting

- SSE is a **read-only view over job state in SQLite**, never the transport of record. Clients send `Last-Event-ID` and the server replays from the database.
- The SSE response sets `Content-Encoding: none` ✅ — Fly's proxy buffers responses before compressing them, which breaks streaming — plus `Cache-Control: no-cache` and `X-Accel-Buffering: no`. `idle_timeout` is raised to 600 and a heartbeat comment is emitted every 15–20s, since a single topic call can exceed 60s with nothing to report.

### Access and spend control

- **Per-person Invite Tokens**, stored in SQLite, individually revocable, replacing any shared password. Spend is attributable per person.
- Opaque 128-bit session ids in SQLite with absolute expiry and a truncatable table for forced logout. Cookies `HttpOnly; Secure; SameSite=Lax; Path=/`. Constant-time comparison. Per-IP login rate limiting with lockout. Same-origin `Origin`/`Sec-Fetch-Site` checks on all mutating endpoints.
- Four layers of spend control: a hard monthly cap set in the Anthropic Console as the outer backstop that survives application bugs; per-call `usage` fields persisted to SQLite with cost computed from a hardcoded price table; a per-job token ceiling enforced at admission; a rolling 24-hour per-user budget and a global daily ceiling that halts the worker. Plus an environment-variable kill switch.

### Retention

- **Retention is split by data class.** Uploaded sources and generated `.apkg` blobs purge on a schedule; the **Card Ledger is never purged**. The two are not the same decision, and conflating them guarantees that any regeneration after the purge window duplicates the user's entire deck.
- The SQLite file is backed up off-platform on a schedule. Fly's volume snapshots are explicitly documented as not a backup, and losing this database has the same effect as purging the ledger.

---

## Testing Decisions

A good test here exercises externally-observable behaviour — what an HTTP client sees, and what Anki does with the file we produce. It does not assert on internal call sequences or private structure.

**Two seams, and only two.**

**Seam 1 — the HTTP boundary.** Everything user-facing is tested through the FastAPI app with a test client: auth, admission control, plan editing, job state transitions, resume after simulated restart, retry semantics, SSE replay, the diff screen, and download.

The only thing faked is **the Anthropic network transport**, via an `httpx` mock transport installed on the SDK client. The real Anthropic SDK stays in the loop, so SDK misuse still surfaces in tests, and the application grows no test-only abstraction of its own. Scripted responses cover the cases that matter: valid plans, malformed cloze markers, refusals, truncation at `max_tokens`, 429s mid-fan-out, and a regeneration that claims a bad `existing_card_id`.

**Seam 2 — the Anki contract.** Generated `.apkg` files are imported into a real Anki collection using the dev-only `anki` package, asserting what only Anki can tell us: that subdeck hierarchy materialises, that GUID-matched notes update in place, that scheduling survives an update, that a notetype change is rejected as conflicting, that cloze notes produce the expected card count, and that media resolves. This seam exists because it catches a whole class of silent failure the HTTP seam cannot observe — every constraint in the identity section above was discovered here rather than reasoned about.

**Deliberately not separate seams.** LibreOffice conversion is exercised through Seam 1 with real fixture files in the container rather than mocked, because its failure modes are silent and a mock would encode the wrong behaviour. Prompt-cache economics are asserted by checking persisted `usage` rows, not by a separate harness.

---

## Out of Scope

- User accounts, registration, billing, or password reset. Access is invite tokens issued by the owner.
- Fetching content from a URL. Uploads and pasted text only — this deliberately excludes HTML extraction, paywalls, and SSRF exposure.
- OCR as a distinct pipeline stage. Scanned pages rely on Claude's vision.
- Pushing cards directly into a running Anki via AnkiConnect.
- Multi-machine or horizontally-scaled deployment. One machine, one volume, one SQLite file.
- Deleting cards from a user's collection. Retired cards are left in place.
- Verified page provenance. `source_page` is self-reported and unverified, because citations and structured outputs cannot be combined.
- Editing an existing Deck's already-exported deck hierarchy. Anki cannot move existing cards on import; users rename inside Anki.

---

## Further Notes

**Image Occlusion** is scheduled last and needs its own ingestion sub-pipeline rather than a flag on the existing one. Anki has shipped a built-in Image Occlusion notetype since 23.10, identified solely by `original_stock_kind == 6` ✅, and genanki can emit it with a small `Model` subclass that injects `originalStockKind` and per-field tags — verified end to end, including that Anki parses the shapes back and renders the masks. The complication is coordinates: Anthropic's documentation states that for PDF document blocks, pages are rasterized server-side at dimensions the caller does not control, so returned coordinates cannot be mapped back onto the page. Occlusion therefore requires rasterizing the diagram locally, sending it as an **image** block, requesting **absolute pixel** coordinates (the docs warn explicitly against asking for normalized ones), normalizing by the pre-resize dimensions in our own code, and storing that same rasterized image as the Anki media file so the masks line up. Coordinate output is documented as approximate, so a drag-to-adjust editor is expected, with Anki's own note editor as the fallback.

**Known risks.**
- genanki is semi-dormant. The dependency is pinned and the cloze bug is worked around rather than waited on.
- The similarity threshold governing slot reuse is the highest-risk tunable in the system: too permissive corrupts review history, too strict silently duplicates. It needs a regeneration test asserting UUID stability across two runs.
- LibreOffice fidelity varies with unusual fonts and embedded objects.
- Fly's SSE behaviour over HTTP/2 has a reported iOS/WebKit delivery lag; the escape hatch is pinning ALPN to HTTP/1.1.

**Cost reference** (Opus 5, $5/$25 per MTok, 1h cache write at 2×):

| Job | Tokens | Approx. cost |
|---|---|---|
| 10-page lecture | ~50k | ~$0.75 |
| 40-page chapter | ~200k | ~$3.10 |
| ~140 dense pages | ~700k (admission ceiling) | ~$10 |
