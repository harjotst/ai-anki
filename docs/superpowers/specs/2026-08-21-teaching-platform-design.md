# Design — ai-anki as a teaching platform

**Status:** approved, awaiting spec review
**Date:** 2026-08-21
**Supersedes:** nothing. Extends `docs/spec.md`, which remains accurate for the generation pipeline.

---

## What this changes

ai-anki today is a single-machine tool that turns a document into an `.apkg` file. One
owner mints invite tokens by hand; there are no accounts; studying happens in Anki, on
the user's own device, where this application can never see it.

It becomes a study application that writes its own material. People sign up, are taught
the content they uploaded, review cards inside the app, and compare progress with
friends. Anki export survives as an escape hatch — the way out for people who already
live there — rather than as the product.

Four things follow from that, and each is load-bearing:

1. **The app must own the study loop.** Competition on "cards done" and "topic mastery"
   is not a feature that can be added to a generator. It is a consequence of holding
   every answer somebody has given.
2. **Teaching comes before cards.** The cards reinforce comprehension; they do not
   create it. A user who is handed 164 cards on material they have not understood is
   worse off than one who was taught first.
3. **Identity becomes real.** Invite tokens were built so one owner could hand out
   access to friends. Public signup, payment and a social graph need accounts.
4. **One SQLite file on one machine stops being enough.** Losing that volume today
   loses regenerable decks. After accounts and subscriptions it loses people's logins
   and payment state.

---

## Glossary additions

Extends the glossary in `docs/spec.md`.

| Term | Meaning |
|---|---|
| **Account** | One person, identified by a Supabase `auth.users` UUID. Replaces Invite Token as the unit of ownership and spend attribution. |
| **Lesson** | Generated prose teaching one Topic: concepts in dependency order, worked examples, the misconceptions people actually hit. Written once per Topic, cached, readable offline. |
| **Tutor** | A live conversational agent scoped to one Topic and its source material. Summoned by the user, or by the app when review evidence says a Topic is decaying. |
| **Study Card** | One Account's copy of a Card, carrying scheduling state. Distinct from the Card, which is a generation artifact. |
| **Review** | One immutable record of one answer: card, account, rating, timestamp, elapsed time. Append-only. |
| **Retrievability** | FSRS's probability that a given card would be recalled right now. The basis of Mastery. |
| **Mastery** | Mean Retrievability across the Study Cards of a Topic. What the social features compare. |

---

## Decisions

Each was a genuine fork. The rejected options are recorded because the reasons will
stop being obvious in three months.

### Studying happens in ai-anki, not in Anki

**Rejected:** keeping the app a generator and importing review statistics back from the
user's Anki collection.

Anki holds review data on the user's device. Getting it back means AnkiConnect on
desktop or asking people to upload collection files — which is desktop-only, arrives
stale, is trivially falsifiable, and gives nobody a reason to install a mobile app. The
social features the product is being built around cannot be honest on top of it.

The cost is real: this makes ai-anki an alternative to AnkiMobile and AnkiDroid, which
are mature and one of which is free. The differentiation has to come from the teaching
loop below, not from the scheduler.

### `review` is append-only and authoritative

**This is the decision the rest of the architecture hangs off.** FSRS scheduling state
is *derived* from the review log, never the source of truth.

Three hard problems dissolve:

- **Offline sync needs no conflict resolution.** Two devices cannot disagree about facts
  that have already happened. Merging is the union of two logs, deduplicated by a
  client-generated UUID. No last-write-wins, no vector clocks, no merge policy to get
  subtly wrong.
- **Leaderboards resist forgery** and, more importantly, are recomputable. A bug in
  aggregation is a re-run, not lost history.
- **The scheduler can be replaced.** Re-run a better FSRS over the whole log and
  everybody's cards reschedule correctly.

The cost is storage — one row per answer, forever — which at a few hundred bytes and a
few thousand reviews per user per year is not a real cost.

### Lesson first, tutor on demand

**Rejected:** a live Socratic tutor for everything (every interaction costs tokens,
nothing works offline, and a slow first response on a cold topic is worse than a page
that is already there). **Also rejected:** prepared lessons only (cannot notice a
misunderstanding, which is the only reason to have an agent rather than a document).

Lessons are generated at plan time, once per Topic, cached and readable offline. The
tutor is summoned — by the user when stuck, or by the app when the review log shows a
Topic decaying. Cheap by default; expensive only when it has earned it.

### Supabase for auth and Postgres

**Rejected:** Clerk plus a separate Postgres (better auth UX, but two vendors and
per-user pricing that stings on a consumer app with a free tier). **Also rejected:**
rolling our own OAuth (no vendor cost, but it means personally owning token refresh,
PKCE for the mobile flow, account linking when somebody signs in with Google and later
with Apple, and every breach).

Supabase settles auth and the datastore together. Google, Apple and email sign-in are
built in — Apple is not optional, the App Store requires it once Google is offered — and
the Expo SDK handles the native OAuth flow. Free to 50k monthly active users.

### Expo for the client

**Rejected:** a PWA (cheapest, no platform cut, but iOS PWAs have unreliable background
sync and no App Store discovery, which matters for a product that grows by friends
inviting friends). **Also rejected:** native Swift and Kotlin (best feel, but three
codebases for one developer).

One TypeScript codebase for iOS, Android and web, reusing the React model already in
the repository.

### Platform before teaching

**Recorded as the user's decision against this document's author's recommendation.**

The recommendation was to build the lesson pass first on the existing stack, because it
tests the assumption everything now rests on — whether generated lessons are good enough
to learn from — in days rather than weeks, and no amount of infrastructure work answers
that question.

The user chose to migrate the platform first so nothing is built twice. The mitigation
is a throwaway lesson generated from real material during the migration, so quality is
observed early without maintaining a parallel track.

---

## Architecture

```
Expo client (iOS / Android / web)
    local SQLite  ·  offline study  ·  review log queued for sync
        │
        │  HTTPS
        ▼
FastAPI  ──────────────────────────────►  Anthropic API
    generation pipeline (unchanged)          plan / lesson / cards / tutor
    sync endpoint
    JWT verification
        │
        ▼
Supabase
    Auth      Google · Apple · email
    Postgres  accounts · decks · cards · study state · review log · social
```

The FastAPI service keeps the generation pipeline exactly as it is. Two-pass generation,
prompt-cache lineage, the Card Ledger, slot matching and Anki export are all unaffected
by this work and must stay green throughout it.

---

## Data model

A Card today is a generation artifact owned by a Job. It needs a second life as
something a person studies, and conflating the two would mean a regeneration silently
resetting somebody's scheduling.

| Table | Owns | Lifetime |
|---|---|---|
| `card` | generation output, the Card Ledger | per Job, ledger rows never purged |
| `study_card` | one Account's copy: due, stability, difficulty, lapses, reps | per Account per Card |
| `review` | every answer ever given | append-only, forever |

`study_card` is a projection. It exists because computing FSRS state from the whole log
on every query would be wasteful, not because it is authoritative. It can be dropped and
rebuilt from `review` at any time, and that property is worth a test.

### Sync protocol

The client holds a local SQLite mirror. Answering a card appends a row locally with a
client-generated UUID and a client timestamp. On reconnect:

1. **Push** unsynced reviews. The server inserts them idempotently, keyed on the client
   UUID, so a retried push is free.
2. **Recompute** `study_card` for every affected card, server-side, from the log.
3. **Pull** anything changed since the client's last cursor — new cards, new lessons,
   scheduling recomputed on another device.

Client timestamps are recorded as given and trusted for ordering within one account.
They are not trusted for leaderboards; the server stamps its own receipt time, and
competition uses that.

---

## The teaching loop

```
upload → plan → LESSON per topic → cards → study → failures locate the gap → re-teach
```

Pass 1 already produces a curriculum and currently throws most of it away. The Deck Plan
carries, per Topic: a `::` path, a difficulty rating, a one-sentence rationale for that
rating, and the exclusive list of Claims the Topic owns. That is a syllabus in dependency
order, and it is the input to lesson generation.

**Lesson generation is a third pass.** It sends the same documents with a third JSON
schema, which means — measured against the live API on 2026-08-17, see `app/planning.py`
— it gets its own prompt-cache lineage and shares nothing with pass 1 or pass 2.
Lessons for different Topics *do* share with each other, so the same pacesetter-then-
fan-out shape the worker already uses applies unchanged.

**The tutor closes the loop.** A conventional AI tutor never learns whether it succeeded.
This one has evidence: a card repeatedly rated *again* is a signal the teaching failed,
not merely that memory faded. The trigger condition — how many lapses, over what window,
before the app offers to re-teach — is deliberately left to Spec 4, when there is real
review data to tune it against. Guessing it now would be guessing.

---

## Mastery

Defined precisely, because "topic mastery" is otherwise a marketing word and the social
features would be built on nothing.

**Mastery of a Topic = mean Retrievability across that Topic's Study Cards.**

FSRS already computes retrievability per card — the probability the card would be
recalled right now, given its stability and time since last review. It is the right
measure because:

- It **decays**. Somebody who crammed a topic in March and stopped does not still show
  as having mastered it, which is exactly the honest answer.
- It is **comparable between people** without normalising for how many cards each of
  them generated.
- It needs **no new mathematics**, and it moves for the right reasons.

Cards-done counts are also kept, because they are what people actually enjoy competing
on, but they are a volume measure and are labelled as one.

---

## Membership

Deferred to its own spec, but the shape is determined by where cost actually falls.

Generation costs real API money — a 24-topic run measured at $2.75, and lessons roughly
double that. Studying costs nothing but storage. So:

- **The free/paid line is generation volume**, not study features.
- **Social features stay free.** They are the growth mechanism; charging for them taxes
  the thing that brings users in.
- **Tutor conversations are metered**, because they are the one study-side feature with
  a per-use cost.

---

## Decomposition

Six specs. Each is independently shippable and gets its own design and plan.

| # | Spec | Depends on | Rough size |
|---|---|---|---|
| 1 | **Accounts and the Postgres platform** | — | 2–3 weeks |
| 2 | **Lessons and the tutor** | 1 | 2 weeks |
| 3 | **Study engine** — FSRS, review log, sync API | 1 | 2–3 weeks |
| 4 | **Expo client** | 1, 3 | 3–4 weeks |
| 5 | **Social** — friends, leaderboards, mastery | 3, 4 | 1–2 weeks |
| 6 | **Membership** | 1, and knowing what people pay for | 1 week |

Spec 1 is detailed in `2026-08-21-accounts-platform-spec.md`.

---

## Risks

**The thesis is untested until week 4.** Generated lessons may not be good enough to
learn from. If they are not, the product is a card generator with an expensive account
system attached. Mitigated only partially by generating a sample lesson early.

**This competes with free, mature software.** AnkiDroid is free and open source;
AnkiMobile is a one-off purchase from a fifteen-year-old ecosystem. A worse scheduler
with a better tutor is a coherent bet, but it is a bet.

**Two things built today get rewritten.** The off-platform backup module targets
SQLite's `VACUUM INTO`, which does not exist in Postgres; its S3 upload, retention and
pruning logic survives, the snapshot mechanism does not. The invite and owner-token
system is deleted outright.

**Cost per user rises sharply.** Generation roughly doubles with lessons, and the tutor
adds an unbounded conversational cost on top. The existing budget controls — per-job
token ceiling, rolling 24-hour caps, kill switch — were designed for a handful of
invited friends and will need revisiting against a public free tier.

---

## Explicitly out of scope

- Migrating the existing local test data. It is test data; it will be discarded.
- Anything about the Anki export path, which is finished and stays as it is.
- Real-time multiplayer study. Competition is asynchronous — leaderboards, not races.
- Content moderation and copyright policy for uploaded material. This becomes a real
  question the moment signup is public, and it is a policy question rather than an
  engineering one.
