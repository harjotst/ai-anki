# ai-anki UI Redesign — Final Design Brief

**Status:** Definitive. This supersedes the audit and the three exploratory directions.
**Scope:** Web UI rebuild inside the existing Vite + React 18 app. No backend changes. No framework change.
**Verified against:** `frontend/package.json` (Vite 6, React 18.3, no router dep), `frontend/src/App.jsx` (1601 lines, boolean-state navigation), `frontend/src/style.css` (163 lines, single light palette).

---

## 1. Chosen direction: Vitals

The two judges split 1–1 (Ember 43/42, Vitals 41/43 — a combined 85 vs 84 dead heat), and both observed that all three directions converged on identical architecture: Today-first inversion, pipeline demoted to status chips, offline-optimistic review queue against the already-idempotent `POST /api/reviews`, one plain-value token file, one shared route table. So the choice is register and risk, and under this project's *actual* constraints — one developer, no new backend work, no framework change — **Vitals wins**: it has the smallest mechanic surface (no rest-day banking logic to invent, no activity-mined time estimates to validate, one animation, one accent), its guardrails are structural (a lint rule, a ban list) rather than editorial discipline that erodes PR by PR, its borders-not-shadows elevation model is the most React-Native-portable of the three, and its clinical-instrument register — "AMBOSS, not Duolingo" — is the one least likely to age or to insult an adult professional. Ember's genuinely superior loop features do not require Ember's identity; they graft into Vitals for roughly a day of work each, and are grafted below. What made Judge 1 pick Ember (streak survival on a 24-hour call, catching bad AI cards inside the daily loop) is fully absorbed by grafts G1 and G2.

---

## 2. Grafts (named, sourced, binding)

These are part of the spec, not suggestions:

- **G1 — "Review misses" (from Ember).** Session-complete screen lists the session's Again-rated cards with per-card Edit/Flag. This is the dedicated moment where AI-generated card errors get caught inside the daily loop, instead of in a QA screen nobody revisits.
- **G2 — Banked rest days (from Ember).** Every 7 consecutive study days banks one silent streak cover, max 2 banked. Computed client-side from `/api/me/activity` history (display-level grace; the server streak is untouched). Copy in Vitals' quiet register: "Day 12 · 1 rest day banked" / "Day 12 held — a rest day covered Tuesday." No flame glyph.
- **G3 — Evening streak-expiry state (from Ember).** After 8 pm local with zero reviews today, the streak chip switches from filled to outline with "expires 11:59 pm". Pure status, no nag; cheapest retention lever in any of the three specs.
- **G4 — Engineering ban list + font fallback posture (from Ember).** Written repo rule: no `<table>`, no `position: sticky`-dependent layouts, no hover-only affordances, no dark-theme shadows (fill steps instead), no browser-only primitives outside an adapter seam. Fonts: Inter via Google Fonts on web with a `system-ui` fallback stack; if Inter's tabular numerals fail verification on Hermes/expo-font later, the RN theme drops to the system stack rather than shipping proportional stats.
- **G5 — 7-day due-forecast strip (from Night Shift).** Beneath the Today heatmap: "tomorrow 42 · Sun 15 · …" — turns the FSRS schedule into an exam-planning tool. **Feature-detected:** rendered only if `/api/me/activity` (or the `/due` payloads) actually carries per-day future aggregates; otherwise degrade to Vitals' next-due-time line. No backend change is authorized to make this exist.
- **G6 — Card-info panel (from Night Shift).** Study-session overflow menu gains "Card info": stability, due date, lapses — whatever fields the `/due` card payload already carries. The scheduler transparency that earns an Anki-native's trust in FSRS. Feature-detected against the payload; fields absent are omitted, never faked.
- **G7 — "Sort by biggest gap" (from Night Shift).** Compare screen gets a sort toggle: topic order / biggest gap. "Where is Sam beating me" is the grinder's actual question. Nearly free.
- **G8 — Hex lint rule (native to Vitals, elevated to CI).** A lint/CI grep fails the build if any hex literal appears outside `tokens.json` and its generated outputs. The dual palette and RN parity die from one stray hex; this is a CI problem, not a discipline problem.
- **G9 — Native share-sheet integrations (from Night Shift/Ember), deferred.** When the RN app is built: `.apkg` export via the OS share sheet (opens directly in AnkiMobile/AnkiDroid), and the app registered as a share-sheet target for PDF intake. Recorded here so the web `upload()` and `download()` wrappers stay behind a seam (see §8).

Held in reserve, not in this build: Ember's foregrounded weekly-race hero on Today (re-evaluate as an experiment once retention data exists) and Ember's time-priced sessions ("~11 min"), which ship count-only until real per-user seconds/card data supports the estimate — a wrong number erodes trust faster than no number.

---

## 3. Information architecture

### 3.1 The route table (the shared contract)

Navigation is a **route table** implemented on web now, and mirrored verbatim by the future RN/Expo app later. On web it is implemented with `react-router-dom` (a dependency added to the existing Vite app — a library, not a framework change) using real `pushState` routes, so browser back/forward, Android back, and deep links work on every screen. A redirect shim maps legacy `?job=X` URLs to `/job/X`.

```
Tabs (persistent shell)
  /today                      Today — due count, streak, heatmap, decks
  /decks                      Deck library
  /leaderboard                Leaderboard + friends + compare entry
  /you                        Display name, theme, linked sign-ins, sign out

Stacks (push OVER the shell; full-screen; top-left back chevron)
  /deck/:id                   Deck detail (segments: Topics | Cards | History)
  /deck/:id/topic/:topicId    Lesson reader for an owned deck's topic
  /study/:deckId              Study session (full-screen mode, shell hidden)
  /study/all                  Cross-deck chained session
  /job/:id                    Job pipeline — renders by state:
                              upload | planning | plan review | generating |
                              interrupted | failed
  /job/:id/lessons            Lesson reader (post-generation flow)
  /job/:id/cards              Card review (post-generation QA)
  /compare/:deckId            Topic-by-topic compare on a shared deck
```

Study sessions, the lesson reader, and the job pipeline are **modes, not places**: they render full-bleed with the shell hidden. Everything else lives under the shell. Session/summary state survives navigation (exiting a study session and returning resumes it).

### 3.2 Mobile model (design target; RN later, narrow web now)

Bottom tab bar, 4 tabs: **Today, Decks, Leaderboard, You** — line icons + labels, 44pt targets. The Leaderboard tab carries a numeric badge for pending friend requests (from the `/api/friends` payload the app already fetches). Upload is deliberately **not** a tab: a "+" icon in the top bar of Today and Decks, plus "Add lecture" inside deck detail (pre-selecting that deck). The rarest action occupies zero shelf space.

### 3.3 Web adaptation

- **< 768px:** identical bottom tab bar. Every screen must work at 375px — this is the acceptance width.
- **≥ 768px:** the tab bar becomes a left rail — 220px, icon + label, "+ New deck" button at top, streak chip pinned at bottom; collapses to a 72px icon rail between 768–1024px.
- Content column max-width 720px (lesson body 680px). Study renders as a centered 560px column with keyboard hints visible under the rating buttons.
- Every screen gets a **top-of-screen** title and back affordance. Bottom-of-page Back buttons are abolished.
- Wide content (any list that could overflow) sits in an `overflow-x: auto` container; the page body never scrolls horizontally.

### 3.4 Full screen inventory

| Screen | Route | Notes |
|---|---|---|
| Today | `/today` | Opening screen, always |
| Deck library | `/decks` | Yours + Shared with you |
| Deck detail | `/deck/:id` | Topics / Cards / History segments; absorbs rename, share, export, delete, run history |
| Lesson reader (deck) | `/deck/:id/topic/:tid` | Same reader component as the job flow |
| Study session | `/study/:deckId`, `/study/all` | Full-screen mode |
| Session complete | in-stack after study | Stats, misses, next-deck chain |
| Job pipeline | `/job/:id` | Upload / planning / plan review / generating / interrupted / failed |
| Lesson reader (job) | `/job/:id/lessons` | Paged topics, bottom-sheet list |
| Card review | `/job/:id/cards` | QA; terminal CTA = Study now |
| Leaderboard | `/leaderboard` | Leaderboard + friend code + requests + compare entry |
| Compare | `/compare/:deckId` | One friend at a time |
| You | `/you` | Display name, theme (System/Dark/Light), linked sign-ins, sign out |

---

## 4. Screen-by-screen spec (nine key screens)

### 4.1 Today (`/today`)

Answers the only question a daily user has: *what's due, and is my streak safe?*

Top to bottom:

1. **Top bar.** "Today" + date left. Right: streak chip — "Day 12" inside a 3px accent ring that visibly closes as today's reviews accumulate toward the trailing-average goal; when ≥1 rest day is banked, a small "· 1 rest day" suffix (G2); after 8 pm with zero reviews today, the chip flips to outline style with "expires 11:59 pm" (G3). Far right: "+" upload icon → `/job/new`-equivalent (a fresh `/job/:id` in upload state).
2. **Hero card** (surface, radius 16, padding 24). A 40px tabular numeral — "37" — with caption "cards due · 3 decks", and a full-width accent button **"Start reviewing"** → `/study/all`, which chains due decks largest-first (client-side: for each deck with due > 0, `POST /decks/{id}/study` if needed, then merge queues). No minutes estimate in v1 (see §2 reserve). **Zero-due state:** "All clear" — plus "next 18 due at 6:00 pm" *only if* the `/due` payload exposes a next-due timestamp — and a ghost "Study ahead".
3. **Attention strip** — present **only** when a job needs the user; accent-soft banner rows directly under the hero: "Cardio — plan ready → Review plan", "Renal — interrupted at topic 14 → Resume", "Pharm — failed: token limit → Retry" (with the actual error). This replaces the permanent "Your runs" panel entirely; the word "runs" is abolished from the UI. Completed jobs never appear here — they fold into deck History (§4.5).
4. **Heatmap card.** 12 weeks × 7 days of 10px cells on the 5-step accent ramp (heat-0…heat-4), from `/api/me/activity` (currently never called anywhere — this is its home). Caption: "214 reviews this week". Beneath it, the **7-day forecast strip** (G5): "tomorrow 42 · Sun 15 · …" — feature-detected; degrades to the next-due line or disappears.
5. **Deck rows.** Name; accent-soft due pill ("12 due"); secondary line "340 cards · studied 2h ago"; chevron → `/deck/:id`. An in-flight job renders as a quiet progress chip on its target deck's row ("writing 14/24", live via SSE). Sorted due-count descending.

**Due counts with no backend change:** on load, `GET /api/decks`, then parallel `GET /api/decks/{id}/due` via `Promise.allSettled`, cached 60s. Acceptable to ~20 decks; the N+1 is acknowledged and `due_count` on `GET /api/decks` is the first item on the backend wishlist (§8) — but nothing here blocks on it.

**States.** Loading: skeleton hero + three skeleton rows — never the empty-account layout (kills the returning-user flash). First-run: hero replaced by a 5-line flow preview (Upload → Approve plan → Read lessons → Review cards → Study daily), a "Try the sample deck" row (a pre-seeded shared deck; no backend change — a normal deck shared by a house account, or omitted if unavailable), and primary "Upload a lecture". Error: inline error card with Retry — never a silent empty state.

### 4.2 Study session (`/study/:deckId`, `/study/all`)

Full-screen mode, shell hidden.

- **Top:** X (exit; session state persists, no confirm) · deck name · "⋯" overflow: **Edit card** (sheet → existing PATCH), **Flag**, **Card info** (G6: stability, due date, lapses — only fields the payload carries), **Undo last**. Below: 2px hairline progress bar with "12 / 37" caption; a small warning-soft sync pill appears only when the local queue is unflushed ("syncing 3" / "offline · 14 queued").
- **Center:** the card. Front is `rendered_front`; after reveal, a hairline divider, then the back rendered through the **same renderer** (fixes raw-markup backs everywhere; the shared renderer is one component used by Study, Card review, and the card browser). 18px/1.5, scrollable when long.
- **Bottom, pinned to safe area (thumb zone):** pre-reveal, a full-width **"Show answer"** (Space/Enter). Post-reveal, four equal-width ≥48pt buttons in a flex row (no grid): **Again / Hard / Good / Easy** — Good filled accent, Again danger-tinted text, Hard/Easy neutral. Beneath each label, its FSRS next-interval preview ("10m / 1d / 4d / 9d") — **feature-detected**: computed by a client-side FSRS mirror (`ts-fsrs` with parameters verified identical to the backend scheduler) from the FSRS state in the `/due` card payload; if the payload lacks the state or verification fails, the hints are hidden, never guessed. Keys 1–4 on web; key hints rendered under the labels at ≥768px only.

**Behavior — the core loop is never blocked by network:**
- Rating advances **optimistically**. Each review is appended to a persisted local queue (`localStorage` on web, behind a storage seam for RN's SQLite/AsyncStorage later) and flushed in batches to `POST /api/reviews` with `client_uuid` — the endpoint is already batch, idempotent, and offline-sync-ready. Retry on reconnect and on tab focus. `client_uuid` comes from a shared `uuid()` helper (web: `crypto.randomUUID` with fallback; the helper is the seam expo-crypto fills later).
- **Undo (Z / Ctrl+Z / overflow):** supersedes the last rating even after the batch has flushed — a superseding review is sent, per Vitals' semantics — because on hospital wifi the flush timing is invisible and undo must not silently stop working.
- **Again/Hard re-queue** into the session locally (conservative short-term steps: Again returns after ~10 cards, Hard at end of queue), and the server's next-due always wins on reconcile — the local step is session convenience, not scheduling authority.
- On queue exhaustion, refetch `/due` once and continue if anything remains.
- Keyboard: Space/Enter reveal · 1–4 rate · Z undo · E edit · F flag.

### 4.3 Session complete (in the study stack)

Centered column:

1. A thin accent ring draws closed once (400ms — **the app's only animation**).
2. "Session complete".
3. 2×2 stat grid, tabular numerals: **Reviewed 37 · Correct 89% · Time 11:42 · Streak "Day 12 kept"** (or "Day 12 held — a rest day covered Tuesday", G2).
4. Secondary line: "Known 412 (+9) · Sam is 23 reviews ahead this week" (from `/api/leaderboard`, when friends exist).
5. **Review misses (G1):** when the session had Again ratings, a collapsed list — "3 cards missed ▸" — expanding to each missed card (front + back via the shared renderer) with per-card **Edit** and **Flag**. This is where bad AI cards die.
6. Forecast line: "Tomorrow: 42 due" (feature-detected, G5-degraded).
7. Buttons: primary **"Next: Pharmacology — 11 due"** when other decks have due cards (chains the cross-deck queue); else "Done". Ghost "Back to Today". Entering study with nothing due shows this same frame with the next-due line.

### 4.4 Deck library (`/decks`)

Top bar: "Decks", search icon (field appears past 6 decks), "+". Two sections: **Yours**, then **Shared with you** (rows subtitled "from Sam" via `owner_name`). Row anatomy identical to Today's deck rows (name / due pill / "N cards · studied 2h ago" / chevron), plus a "shared" badge listing recipients on decks you've shared. Sorted due-count descending. Whole row navigates to deck detail — **no inline actions, no inline rename** (blur-save is dead; rename moves to deck detail). Empty state: sample deck card + "Add your first lecture".

### 4.5 Deck detail (`/deck/:id`)

This screen absorbs rename, export, sharing state, card browsing, mastery, and run history — everything the audit found homeless.

- **Header:** back chevron, deck name, meta "412 cards · 24 topics · shared with Sam, Priya". "⋯" menu: **Rename** (dialog with explicit Save/Cancel; failure shows an inline error, never a silent revert), **Delete** (typed-confirm — type the deck name).
- **Primary button:** "Study 12 due" → `/study/:id`. Zero-due: quiet style showing "next due 6 pm" (when available) + ghost "Study ahead". The button has a pending state while enroll runs and an error toast on failure — no more dead-feeling taps.
- **Action row** (44pt icon buttons): **Add lecture** (opens the job upload with this deck pre-selected), **Share** — *always visible*: with zero friends it opens a sheet explaining "Share needs a friend first" linking to Leaderboard's add-friend flow; after sharing, a "Shared with Sam" toast and the recipient list updates in place, with per-person unshare — **Export .apkg** (file named after the deck, never a UUID fragment).
- **Segmented control: Topics | Cards | History.**
  - **Topics:** one row per topic — read/unread lesson dot (read state persisted locally), topic name disambiguated with parent path when leaf names collide, mastery bar + tabular "82%" from `GET /mastery` (finally used for the user's own study, not just friend-compare), due chip when > 0. Tap → lesson reader. **Copy rule:** low retrievability after a gap is "due for review", never "forgotten".
  - **Cards:** searchable list from `GET /cards`; tap → edit sheet (existing PATCH); per-card flag/delete.
  - **History:** this deck's jobs folded in — completed collapse to one line each; failed rows show the actual error + Retry; interrupted rows show Resume. Run history lives here, not on Home.

### 4.6 Job pipeline (`/job/:id`, rendered by state)

- **Upload.** Destination selector first (New deck + name field / existing-deck picker, pre-filled when launched from deck detail). Web: styled drag-and-drop zone (dashed panel, "Drop a lecture PDF or browse") — the `<input type=file>` lives behind an `upload()` adapter seam (RN's document picker/camera fills it later, G9). File chip with name + size + remove; determinate progress bar; Cancel; **input value reset after every attempt so retry always fires**. Primary: "Upload & plan".
- **Planning.** SSE-driven status line ("Reading 42 pages…") with an indeterminate spinner floor. **No hard-coded time claims anywhere in the pipeline.** Polling is replaced by the existing SSE stream while the page is visible; one refetch on tab focus.
- **Plan review.** Pinned top summary: "24 topics · ~380 cards · est $0.42" — on estimate-fetch failure, an explicit "estimate unavailable — you can still generate" banner, never silence. Body: **one card per topic, no table** (this card layout *is* the phone layout): title text input · difficulty segmented control (easy/medium/hard) · type segmented control (basic/cloze) · card-count stepper (−/+) · **Remove renders as strike-through with Restore, applied only on Approve** (drops are undoable; an accidental tap loses nothing). "+ Add topic" row at the end. Over-limit state lists the job's actual files with per-file remove controls — the copy never references controls that don't exist. Desktop lays the same cards 2-up. **Bottom-pinned bar:** live totals + primary "Approve & generate".
- **Generating.** SSE-driven per-topic checklist ("✓ Endocarditis · writing Valve disease · 14 of 24"). Primary "Read lessons" enabled from the first streamed lesson; ghost **"Review the cards written so far" always present** — never a disabled primary button. Copy: "You can leave — this keeps running" (strings live in a copy module with per-platform variants; the word "tab" never ships to native).
- **Interrupted** gets its own explicit branch (the state currently matches no router branch and dead-ends on a lying "Working…" panel): "Interrupted at topic 14" + primary **Resume**, wired to the stage-appropriate restart (`POST /plan` or `POST /generate`). The fallback panel never claims fake progress.
- **Failed:** the actual error text + Retry.

### 4.7 Lesson reader (`/job/:id/lessons`, `/deck/:id/topic/:tid`)

- **Top:** back/close; a **"Topic 3 of 24" chip** that opens a bottom sheet (mobile/web narrow) or left sidebar (≥1024px) listing all topics with read checkmarks and per-topic card counts — the flex-wrap chip wall is abolished. Thin progress bar.
- **Body:** rendered lesson, 680px max, 17px/1.6; worked-example blocks on surface-sunken with radius 10; misconception callouts with a 3px accent left border. All restyled from tokens.
- **Bottom bar:** ghost "Previous" / primary "Mark read · Next". Topics are horizontally paged — arrow keys + edge chevrons on web, swipe on mobile widths. **Read state and last position persist locally**; reopening resumes.
- During generation, the sheet shows a trailing "writing topic 15…" item; reading is never blocked. A lessons fetch **error renders a retryable error state** — it never coerces to an empty list and never silently routes to card review; only a server-confirmed zero-lessons job goes straight to card review, and in that case its Done routes home directly (no double-back no-op).
- After the final lesson: terminal card "380 cards ready" → primary "Review the cards".

### 4.8 Card review (`/job/:id/cards`)

- Grouped by topic; section headers stay visible while scrolling (implemented with an RN-legal pattern — list-header pinning, not `position: sticky` on the page). Header per section: topic name · "Select all 12" · **"Reject all 12" moved into a per-section overflow with a confirm dialog** — physically separated from selection.
- **Per-card actions: Keep · Edit · Re-roll · Reject.** Keep is per-card and one tap/keystroke — the missing primitive. Keyboard: J/K move, A keep, R reject, E edit. The **progress bar counts kept cards** — a number the user directly controls.
- Reject = soft-delete with a 5s undo snackbar. Single-card actions (edit save, re-roll, reject) **update that card in place — the selection set survives**; no more losing 40 ticks to one re-roll.
- **Bulk bar is bottom-fixed** (thumb zone), sliding up when selection > 0: "Keep 12 · Reject 12 · 12 selected".
- Fronts *and* backs render through the shared renderer.
- **Terminal region — the pipeline finally lands in the product's own loop:** primary **"Study these now"** (`POST /api/decks/{id}/study` → `/study/:deckId`); secondary ghost "Download for Anki (.apkg)" (named after the deck); tertiary "Later" → deck detail. Copy speaks of *your deck*, never "your Anki collection". The export diff screen branches on the actual no-baseline response vs other errors — network failure gets a Retry state, never a false "everything is new" claim.

### 4.9 Leaderboard & Compare (`/leaderboard`, `/compare/:deckId`)

**Leaderboard.** Title: **"Leaderboard"** — named what it is, in primary navigation, never again a footer ghost button. Pending friend requests: banner at top with inline Accept/Decline; numeric badge on the tab icon (from the `/api/friends` payload already fetched). Main list: rank numeral · display name · three right-aligned tabular-numeral stats with column headers **"Reviews (this wk)" · "Streak" · "Known"** — only Reviews is scoped weekly, and each header carries an ⓘ popover defining the metric (tooltips are click/tap-triggered, never hover-only). Your row highlighted accent-soft. **First visit without a `display_name` opens a set-your-name sheet** (editable later on You) — hex-fragment identities never reach a leaderboard, a share picker, or a compare header. Footer card: friend code in monospace + Copy/Share. Empty state: your own stats row + your code + "Compete with a classmate — send your code" — the tab pays rent solo.

**Compare on a shared deck.** Step 1 — deck picker: **only actually-shared decks** render as full tappable rows (styled as rows, not topic chips); unshared decks appear dimmed with an inline "Not shared yet — Share" action, so the empty case teaches the path instead of dead-ending. Step 2 — **one friend at a time** (kills the unbounded table): segmented chips for ≤3 friends, bottom-sheet picker beyond; horizontal paging between friends. Body: topic rows — parent-path-disambiguated labels (two "Overview"s are never indistinguishable), two stacked horizontal mastery bars: "You 82" (accent) over "Sam 74" (neutral), right-aligned tabular numerals, muted "+8" delta chip when ahead. **Sort toggle: By order / By biggest gap (G7).** `why_empty` responses render as an explanation + inline share CTA. Footer: "Study your weakest topic" deep-links into `/study`.

### 4.10 Cross-cutting standards (address the remaining audit majors/minors)

- **Every fetch gets a catch** that renders an error state with Retry. No eternal spinners (Friends' `Promise.all`, Study's `/due`, CardReview's refresh), no silent empty-looking failures (Home's `loadHome`).
- **Loading skeletons** are visually distinct from true empty states, everywhere.
- **One lightweight toast system** covers: share confirmation, rename failure, study-enroll failure, reject-undo, friend-accept — every currently-silent action gets feedback.
- **Type floor 12px** — the 0.68–0.72rem tier is abolished. **44pt minimum effective touch target** on every interactive element; rating buttons 48pt; chips padded to clear 44pt.
- **Strings module** with per-platform variants; no "tab" copy on native, no pipeline jargon ("runs") anywhere.
- **No hover-only affordances** (the Disconnect `title=` tooltip is replaced by its existing visible paragraph).
- **Seams for the RN future** (no native work now, but nothing that blocks it): `session.js` keeps the OAuth redirect flow on web behind one interface (native `signInWithOAuth` + deep-link redirect and Sign in with Apple slot in later); `upload()` hides the File-vs-`{uri,name,type}` difference; storage access goes through one adapter (web `localStorage` → RN secure-store/AsyncStorage); `uuid()` is a helper, not a global call.

---

## 5. Design tokens

**Source of truth:** `frontend/src/tokens.json` — plain hex and numbers only. A build step emits `tokens.css` (imported by `style.css`) and `tokens.ts` (the future RN theme object imports it directly). **CI rule (G8): any hex literal outside these files fails the build.**

### 5.1 CSS variables (paste-ready)

```css
/* tokens.css — generated from tokens.json. Do not hand-edit colors elsewhere. */

:root {
  /* light */
  --bg: #FAF9F7;
  --surface: #FFFFFF;
  --surface-sunken: #F1EFEA;
  --border: #E3E1DA;
  --border-strong: #C9C6BD;
  --text: #1C1B18;
  --text-secondary: #605D55;
  --text-muted: #8B877D;
  --accent: #0E7C66;
  --accent-hover: #0A6353;
  --accent-soft: #E3EFEB;
  --on-accent: #FFFFFF;
  --success: #33774F;
  --success-soft: #E5F0E6;
  --danger: #A83E36;
  --danger-soft: #F8E9E7;
  --warning: #96690F;
  --warning-soft: #F5EDDA;
  --heat-0: #EDEBE4;
  --heat-1: #CFE4DD;
  --heat-2: #9CCBBE;
  --heat-3: #5BA893;
  --heat-4: #0E7C66;

  /* type (px) — Inter via Google Fonts, system-ui fallback stack */
  --font-sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui, sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, monospace;
  --type-stat-xl: 40px;  --lh-stat-xl: 44px;  --w-stat-xl: 650;
  --type-display: 32px;  --lh-display: 38px;  --w-display: 650;
  --type-title:   22px;  --lh-title:   28px;  --w-title:   620;
  --type-heading: 17px;  --lh-heading: 24px;  --w-heading: 620;
  --type-body:    16px;  --lh-body:    24px;  --w-body:    400;
  --type-secondary: 14px; --lh-secondary: 20px; --w-secondary: 400;
  --type-caption: 12px;  --lh-caption: 16px;  --w-caption: 500;  /* 12px is the floor */

  /* spacing */
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-5: 24px; --space-6: 32px; --space-7: 48px;

  /* radius */
  --radius-sm: 6px;   /* chips, inputs */
  --radius-md: 10px;  /* buttons, rows */
  --radius-lg: 16px;  /* hero cards, sheets */
  --radius-pill: 999px;

  /* elevation: 1px borders everywhere; ONE shadow, reserved for sheets/modals */
  --shadow-sheet: 0 8px 24px rgba(0, 0, 0, 0.18);

  /* touch */
  --target-min: 44px;
  --target-rating: 48px;
}

/* dark — system preference, unless the user chose light */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #131311;
    --surface: #1C1B18;
    --surface-sunken: #0D0D0B;
    --border: #2B2A25;
    --border-strong: #3E3C35;
    --text: #ECEAE3;
    --text-secondary: #A5A198;
    --text-muted: #757168;
    --accent: #3FBFA4;
    --accent-hover: #5ACDB4;
    --accent-soft: #17342D;
    --on-accent: #0A1613;
    --success: #6FBE8B;
    --success-soft: #1A2C20;
    --danger: #E0776C;
    --danger-soft: #362019;
    --warning: #D9AC55;
    --warning-soft: #322A16;
    --heat-0: #1E1D1A;
    --heat-1: #1D3B33;
    --heat-2: #23594C;
    --heat-3: #2E8A73;
    --heat-4: #3FBFA4;
  }
}

/* dark — manual override (toggle on /you, persisted) */
:root[data-theme="dark"] {
  --bg: #131311;
  --surface: #1C1B18;
  --surface-sunken: #0D0D0B;
  --border: #2B2A25;
  --border-strong: #3E3C35;
  --text: #ECEAE3;
  --text-secondary: #A5A198;
  --text-muted: #757168;
  --accent: #3FBFA4;
  --accent-hover: #5ACDB4;
  --accent-soft: #17342D;
  --on-accent: #0A1613;
  --success: #6FBE8B;
  --success-soft: #1A2C20;
  --danger: #E0776C;
  --danger-soft: #362019;
  --warning: #D9AC55;
  --warning-soft: #322A16;
  --heat-0: #1E1D1A;
  --heat-1: #1D3B33;
  --heat-2: #23594C;
  --heat-3: #2E8A73;
  --heat-4: #3FBFA4;
}
```

All stats, counters, intervals, and leaderboard columns use `font-variant-numeric: tabular-nums` (RN: `fontVariant: ['tabular-nums']`).

### 5.2 React Native theme object (generated shape)

```ts
// tokens.ts — generated from tokens.json. Same values, RN-consumable.
export const palette = {
  light: {
    bg: '#FAF9F7', surface: '#FFFFFF', surfaceSunken: '#F1EFEA',
    border: '#E3E1DA', borderStrong: '#C9C6BD',
    text: '#1C1B18', textSecondary: '#605D55', textMuted: '#8B877D',
    accent: '#0E7C66', accentHover: '#0A6353', accentSoft: '#E3EFEB', onAccent: '#FFFFFF',
    success: '#33774F', successSoft: '#E5F0E6',
    danger: '#A83E36', dangerSoft: '#F8E9E7',
    warning: '#96690F', warningSoft: '#F5EDDA',
    heat: ['#EDEBE4', '#CFE4DD', '#9CCBBE', '#5BA893', '#0E7C66'],
  },
  dark: {
    bg: '#131311', surface: '#1C1B18', surfaceSunken: '#0D0D0B',
    border: '#2B2A25', borderStrong: '#3E3C35',
    text: '#ECEAE3', textSecondary: '#A5A198', textMuted: '#757168',
    accent: '#3FBFA4', accentHover: '#5ACDB4', accentSoft: '#17342D', onAccent: '#0A1613',
    success: '#6FBE8B', successSoft: '#1A2C20',
    danger: '#E0776C', dangerSoft: '#362019',
    warning: '#D9AC55', warningSoft: '#322A16',
    heat: ['#1E1D1A', '#1D3B33', '#23594C', '#2E8A73', '#3FBFA4'],
  },
} as const;

export const type = {
  statXl:   { size: 40, lineHeight: 44, weight: '650' },
  display:  { size: 32, lineHeight: 38, weight: '650' },
  title:    { size: 22, lineHeight: 28, weight: '620' },
  heading:  { size: 17, lineHeight: 24, weight: '620' },
  body:     { size: 16, lineHeight: 24, weight: '400' },
  secondary:{ size: 14, lineHeight: 20, weight: '400' },
  caption:  { size: 12, lineHeight: 16, weight: '500' }, // 12 is the floor
} as const;

export const space = [0, 4, 8, 12, 16, 24, 32, 48] as const;
export const radius = { sm: 6, md: 10, lg: 16, pill: 999 } as const;
export const touch = { min: 44, rating: 48 } as const;
// Elevation: 1px borders on both themes; dark elevates by fill step
// (surfaceSunken -> surface), never by shadow. One shadow token exists,
// reserved for bottom sheets: { offset: {0,8}, radius: 24, opacity: 0.18 }.
```

**Elevation model:** hairline 1px borders everywhere, both themes; dark never uses shadows (fill steps instead, per G4); the single sheet shadow is the only shadow in the system. **Motion:** one animation in the whole app — the 400ms session-complete ring; everything else is instant or a ≤150ms opacity/position ease.

---

## 6. The motivation loop, end to end

The contract: **one glance → one number, closed daily.** Every reinforcement is a numeral, a ring, or a cell. No confetti, mascots, XP, exclamation points, or congratulatory prose longer than one line. The register is a UWorld score report — the feedback dialect this persona already runs on.

1. **Open (10×/day).** Today leads with the due count — the day's work as a finite, precise quantity — and the streak chip, whose ring visibly fills as reviews accumulate. After 8 pm with zero reviews, the chip flips to outline + "expires 11:59 pm" (G3): loss aversion on an earned asset, stated as fact, not a nag.
2. **Start (one tap).** "Start reviewing" chains all due cards across decks. No deciding, no navigating.
3. **During.** The hairline progress bar and FSRS interval previews make every rating feel like calibrated instrument input. Zero network latency inside the loop — the optimistic queue means the machine always responds instantly, even on hospital wifi.
4. **Close.** Session complete pays out in deltas the user caused in the last ten minutes: 89% correct, Known +9, "Day 12 kept", "Sam is 23 reviews ahead this week" — then **Review misses** (G1) turns errors (the user's and the AI's) into a 30-second cleanup instead of eroded trust, and the "Next: Pharm — 11 due" chain captures momentum.
5. **Survive real life.** Banked rest days (G2): 7 consecutive days banks one silent cover, max 2. A 28-hour call does not end a 40-day streak; the copy frames it as recovery, quietly: "Day 41 held — a rest day covered Tuesday." This is the single mechanic that keeps streaks adult.
6. **Tomorrow's hook, three-fold.** The forecast line ("Tomorrow: 42 due") makes skipping a named loss; the heatmap grows one cell per day and an empty cell is conspicuous (the Anki-heatmap habit, native to this persona); and the leaderboard's Reviews column resets Monday — a repeatable weekly race against real classmates, re-enterable by laggards, rather than an unwinnable all-time total.
7. **Compete → study.** Topic compare converts a friend's lead into a targeted action: gap sort (G7) answers "where is Sam beating me", and "Study your weakest topic" ends every comparison in studying, not in a table.
8. **Later, on mobile (out of this build):** one quiet morning push at a user-chosen time — "Day 13 · 42 due" — and nothing else.

**Copy rules (binding):** decayed retrievability is "due for review", never "forgotten"; streak-at-risk is status, never guilt; deletion is confirmed, never celebrated.

---

## 7. Build order (web rebuild, smallest coherent slices first)

Each slice ships independently and leaves the app working.

1. **Slice 1 — Tokens + dark mode.** Create `tokens.json` + the build step emitting `tokens.css`/`tokens.ts`; sweep every literal hex in `style.css` into semantic tokens; add the dark palette (system + manual toggle, persisted); add the CI hex-lint rule (G8) and the engineering ban list (G4) to the repo. *Delivers the persona's #1 stated want (dark mode) in the first slice and locks the system of record before anything is built on it.*
2. **Slice 2 — Router + shell + feedback primitives.** Add `react-router-dom`; implement the route table (§3.1) and the shell (bottom tabs < 768px, left rail ≥ 768px); legacy `?job=` redirect; top-of-screen back everywhere; the toast system; the shared error-state-with-Retry and skeleton components. *Fixes broken back, unfindable leaderboard, and silent failures as a class.*
3. **Slice 3 — Study loop.** Rebuild `/study/:deckId`: optimistic advance + persisted batch queue + supersede-undo; keyboard bindings; Again/Hard re-queue; interval previews and Card info (feature-detected); edit/flag overflow; shared card renderer (front and back); session complete with stats, Review misses, and next-deck chain. *The highest-frequency surface, fixed third because it depends on slices 1–2.*
4. **Slice 4 — Today.** Hero due count (parallel `/due` fetches, cached), `/study/all` chaining, streak chip with ring + evening state + rest-day display, heatmap from `/api/me/activity`, forecast strip (feature-detected), attention strip, deck rows with due pills, first-run and skeleton states.
5. **Slice 5 — Deck library + deck detail.** Library sections; deck detail with Topics/Cards/History segments, mastery bars, card browser, always-visible Share with feedback, named `.apkg` export, rename dialog, typed-confirm delete, run history folded in.
6. **Slice 6 — Pipeline.** Upload drop zone with progress/cancel/reset; SSE-driven planning and generating states; plan review as card-per-topic with undoable drops, add-topic, honest estimate states; explicit interrupted (Resume) and failed (error + Retry) branches; lesson reader with sheet navigation, paging, persisted read state, retryable errors; card review with per-card Keep, keyboard flow, bottom bulk bar, undo snackbar, selection preservation, and the **"Study these now"** terminal CTA.
7. **Slice 7 — Social.** Leaderboard rename + relabeled columns + ⓘ definitions; display-name sheet; pending-request banner + tab badge; friend-code invite states; compare with shared-only picker, one-friend pager, gap sort, inline share CTAs.
8. **Slice 8 — Polish sweep.** Full pass of every screen at 375px; 44pt target audit; 12px type-floor audit; copy-module sweep (no "runs", no "tab", no Anki-collection framing); dark-mode visual QA of every state.

---

## 8. Explicitly OUT of scope

- **No new backend work.** No endpoint, field, or schema changes. Consequences, accepted: Today's due counts come from parallel per-deck `/due` fetches (fine at this deck count); interval previews, card info, next-due times, and the forecast strip are **feature-detected against existing payloads and silently degrade** when the data isn't there — the UI never fakes a number. The moment backend work reopens, the wishlist is, in order: `due_count` + `last_studied` on `GET /api/decks`; next-due timestamp in the `/due` payload; per-day due forecast in `/api/me/activity`; predicted next-intervals in the `/due` card payload (retiring the client-side FSRS mirror).
- **No framework change.** The app stays Vite + React 18. `react-router-dom` is a dependency, not a framework; the expo-router question is deferred entirely to the RN app, which mirrors the route table in §3.1 as its contract. No SSR, no Next, no monorepo restructure.
- **No React Native build in this pass.** Portability is enforced now — token pipeline, route contract, ban list (G4), and the four seams (`session.js` auth, `upload()`, storage adapter, `uuid()`) — so the RN app is a second renderer of a settled design, not a second design.
- **No push notifications** (native-only; noted as the future upgrade in §6.8).
- **No time-priced session estimates** ("~11 min") until real per-user seconds/card data exists; ship count-only.
- **No new gamification** beyond the specified streak/rest-day/heatmap/weekly-race system. No mascots, badges, XP, or confetti — ever, per the copy rules.
- **No sample-deck backend feature.** The first-run sample deck is an ordinary deck shared from a house account; if unavailable, the row is omitted.

---

## Appendix: blocker traceability

| Audited blocker | Addressed in |
|---|---|
| Home organized around pipeline; no due counts anywhere | §4.1 Today (hero due count, due pills, `/study/all`) |
| No app shell; leaderboard buried behind footer ghost buttons | §3 shell + route table; §4.9 Leaderboard as a tab |
| Study missing shortcuts, interval previews, undo, edit/flag | §4.2 (keys, feature-detected previews, supersede-undo, overflow menu) |
| Blocking synchronous `rate()`; silent failure on bad wifi | §4.2 optimistic advance + persisted batch queue + sync pill |
| Zero responsive handling; PlanEditor table; per-friend table columns | §3.3 (375px acceptance), §4.6 card-per-topic plan editor, §4.9 one-friend compare pager, §4.10 targets/type floor |
| Pipeline dead-ends at .apkg download; no path into in-app study | §4.8 "Study these now" terminal CTA; export demoted |
| `interrupted` state falls through to a lying "Working…" panel | §4.6 explicit Interrupted branch with Resume |
| `<input type=file>` as the front door (web UX + RN impossibility) | §4.6 drop zone + `upload()` seam; G9 deferred native intake |
| OAuth redirect flow impossible in RN | §4.10 / §8 — `session.js` seam now; native auth deferred with the RN app |
| Boolean-state navigation, `replaceState`, broken back, nothing linkable | §3.1 real routes via react-router; legacy `?job=` shim |
| No dark mode; hex literals outside tokens | §5 dual palette + manual override; G8 CI lint rule |

All audited majors and minors are covered by §4.1–§4.10 (each screen spec incorporates its findings) and the cross-cutting standards in §4.10.