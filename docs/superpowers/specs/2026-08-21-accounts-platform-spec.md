# Spec 1 — Accounts and the Postgres platform

**Status:** implemented, except the two verifications that need a live Supabase project
**Date:** 2026-08-21
**Parent design:** `2026-08-21-teaching-platform-design.md`
**Depends on:** nothing
**Blocks:** every other spec

---

## Goal

Replace owner-minted Invite Tokens with real accounts, and one SQLite file on one
machine with managed Postgres — without changing a single thing about how documents
become decks.

The generation pipeline is finished and correct. Two-pass generation, prompt-cache
lineage, the Card Ledger, slot matching, the deck diff and Anki export must all still
work identically when this is done. **The 219 existing tests are the specification of
that, and they drive HTTP rather than SQL, so they should survive the datastore change
essentially unedited.** Any test that needs rewriting is a signal that it was coupled to
SQLite, and that coupling is the thing to fix.

## Non-goals

- Lessons, the tutor, FSRS, the review log, sync, friends, leaderboards, payment.
- Any change to prompts, schemas, caching or the worker's fan-out shape.
- Migrating existing local data. It is test data and will be discarded.

---

## Success criteria

1. A person signs in with Google on the web app and reaches their own decks.
2. A person signs in with Apple, having previously used Google with the same email, and
   arrives at the **same** account rather than a second one.
3. All existing tests pass against real Postgres, with no test knowing that Postgres is
   what it is talking to.
4. `x-owner-token` no longer exists anywhere in the codebase.
5. A job started before a deploy is still resumable after it.

---

## Design

### Identity

Supabase Auth owns credentials. This application owns everything about a person that is
not a credential.

```
auth.users            (Supabase-managed: id, email, provider identities)
    │  1:1
    ▼
public.account        (ours: id → auth.users.id, display_name, is_admin,
                       created_at, signup_source)
```

`account.id` is the Supabase `auth.users` UUID, not a separate key. There is no mapping
table and no second identifier, because two identifiers for one person is how accounts
get orphaned.

An `account` row is created lazily on first authenticated request rather than by a
database trigger on `auth.users`. A trigger would put application logic in a place the
test suite cannot easily reach and the migration tooling does not own.

**Account linking** is handled by Supabase, which links identities sharing a verified
email. This must be verified against a real project rather than assumed — sign in with
Google, sign out, sign in with Apple using the same address, and assert one `account`
row. Success criterion 2 exists because getting this wrong silently creates duplicate
people, and it is discovered months later when somebody's decks vanish.

### Authentication in FastAPI

Supabase issues a JWT. FastAPI verifies it and resolves an account.

- Verify with **JWKS** (asymmetric), not the shared HS256 secret. A leaked shared secret
  mints valid tokens for every user; a leaked public key does nothing.
  ✅ **Verified against the live project on 2026-08-22.** The endpoint is
  `{issuer}/.well-known/jwks.json`, which is exactly what `identity.from_env` builds by
  default. The published key is **ES256** — an elliptic-curve key, not RSA — which
  `verify` already accepts. Checked further than "it parses": a token signed with a
  different key but carrying the project's genuine `kid` is refused.
- Cache the JWKS in-process with a bounded TTL and refetch on an unknown `kid`, so key
  rotation does not require a deploy.
- The bearer token comes from the `Authorization` header. **The session cookie is
  deleted**, along with `app/auth.py`'s session table, login-failure lockout, and
  digest-comparison machinery — Supabase owns all of it now.

The existing `invite_of` FastAPI dependency becomes `account_of` and returns an
`Account`. Its shape is deliberately identical so that route signatures barely change:

```python
async def account_of(request: Request) -> Account: ...
```

Every route currently depending on `invite_of` switches to `account_of`. That is a
mechanical edit across roughly twenty routes and is the bulk of the diff in `main.py`.

### Admin

`x-owner-token` is deleted. `/api/spend`, `/api/maintenance/purge` and
`/api/maintenance/backup` are guarded by `account.is_admin` instead.

The first account created in a fresh database is made admin automatically, and only if
no admin exists yet. Any later promotion is a manual SQL statement, deliberately: an
in-app "make admin" surface is a privilege-escalation feature nobody asked for.

### Ownership columns

`job.invite_id` and `deck.invite_id` become `account_id UUID REFERENCES account(id)`.
`api_call` attribution follows the job, unchanged.

Every query that scopes by invite scopes by account instead. There are eleven of them;
they are listed in the implementation plan. **This is where a mistake leaks one person's
decks to another**, so every one of them keeps a test that asserts a second account
cannot see the first's data. Those tests already exist for invites and are ported rather
than rewritten.

### Schema port

| SQLite | Postgres |
|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `GENERATED ALWAYS AS IDENTITY` |
| `REAL` timestamps | `TIMESTAMPTZ` |
| `TEXT` ids | `UUID` where they are UUIDs, `TEXT` where they are not |
| `PRAGMA journal_mode`, `busy_timeout`, `foreign_keys` | deleted — none apply |
| `BEGIN IMMEDIATE` | plain `BEGIN`; Postgres does not need the escalation |
| `INSERT OR REPLACE` | `INSERT … ON CONFLICT … DO UPDATE` |
| `db.MIGRATIONS` hand-rolled list | a real migration tool |

**Timestamps are the trap.** The codebase stores `time.time()` floats in some columns
and `datetime('now')` strings in others, and compares them in both Python and SQL. Every
one becomes `TIMESTAMPTZ`, and every comparison is checked. A silent timezone bug here
surfaces as backups pruned early or budgets resetting at the wrong hour.

Migrations move to a real tool rather than the additive-statement list added on
2026-08-21. That list was correct for one machine with no downtime window; it cannot
express a rename, a backfill or a rollback, all of which this work needs.

### The worker

**Corrected on 2026-08-21, during implementation.** The spec originally claimed
`SELECT … FOR UPDATE SKIP LOCKED` would replace `worker_id` and delete around
eighty lines. That was wrong on both counts and is recorded rather than quietly
dropped.

`SKIP LOCKED` is for pulling work off a queue. This application has no queue:
a job is started by an HTTP request and runs in that process. Nothing polls for
work, so there is nothing for `SKIP LOCKED` to skip.

What `worker_id` and `recover_orphans` actually solve is a different problem —
"this job says it is generating, and no process is running it" — and they solve
it correctly for one machine, which is what this spec deploys. The multi-machine
answer is a lease with a heartbeat, where a job whose lease has expired is
reclaimable. That is new machinery, it buys nothing until a second machine
exists, and building it now would be exactly the speculative work this plan
says to avoid.

`recover_orphans` is also about thirty lines, not eighty.

Left as it is. Revisit when there is genuinely a second machine, and build a
lease then.

### Backups

Supabase manages point-in-time recovery. The off-platform copy still has a job to do —
vendor independence, not redundancy — so `app/backup.py` is retargeted rather than
deleted:

- `snapshot()` becomes `pg_dump --format=custom` instead of `VACUUM INTO`.
- Upload, date-sorted keys, fourteen-day retention and listing-driven pruning are
  **unchanged**, including their tests.
- `db.backup_to` and the `VACUUM INTO` path are deleted.

### Test harness

This is the largest single piece of work and the one most likely to be underestimated.

- **testcontainers-python**, one Postgres container per test session. Docker is confirmed
  working on this machine and is available in GitHub Actions.
- Isolation is a **fresh schema per test**, created and dropped around each one. A
  transaction-rollback fixture is faster but breaks any test whose code commits — which
  includes every test touching the worker.
- The `boot()` fixture keeps its current contract: calling it twice is a machine
  restart, and the second call must see exactly what the first left behind. This is what
  the durability tests are built on and it must not change.
- `ClaudeScript` is untouched. Faking only the Anthropic network transport was the right
  seam and this work does not disturb it.

Expected: CI gets slower — container startup plus per-test schema creation. If the suite
goes past about ninety seconds, switch to a template database and `CREATE DATABASE …
TEMPLATE`, which is markedly faster than re-running the schema.

---

## Order of work

Each step ends with a green suite. No step leaves the repository broken.

1. **Postgres test harness alongside SQLite.** Parameterise the fixture so the suite runs
   against both. Everything stays green on SQLite while Postgres is brought up. This is
   the step that makes every later step safe.
2. **Port the schema and the SQL.** Fix what the Postgres run reveals, one file at a
   time, until both backends pass.
3. **Delete SQLite.** Drop the parameterisation, the pragmas, `db.backup_to`.
4. **Simplify the worker** onto `FOR UPDATE SKIP LOCKED`. Delete `worker_id` and
   `recover_orphans`.
5. **Add `account`, JWT verification and `account_of`.** Invites still work; both
   credentials are accepted for exactly one commit.
6. **Switch ownership columns** to `account_id`. Port the access-control tests.
7. **Delete invites and `x-owner-token`.** Move admin onto `is_admin`.
8. **Wire the web client to Supabase Auth.** Google and Apple buttons replace the token
   box.
9. **Retarget `backup.py`** to `pg_dump`.

Steps 1–4 are the datastore. Steps 5–8 are identity. They are separable, and if the work
has to be paused, pausing after step 4 leaves a coherent system.

---

## Risks

**Timezone and timestamp drift.** The most likely source of a silent, late-discovered
bug. Every timestamp column and comparison is audited in step 2, not assumed.

**Account linking behaves differently from the documentation.** Verified against a real
Supabase project in step 5, before ownership columns move. Discovering it after step 6
means duplicate accounts already own decks.

**Suite runtime.** 219 tests against a real database, currently 14 seconds against
SQLite. Mitigation is the template-database approach, held in reserve.

**Supabase as a single point of failure.** Auth and data behind one vendor is the
tradeoff accepted for one integration instead of two. The off-platform `pg_dump` is the
hedge: it means the data can leave, even though the logins could not follow it without
work.

---

## Open questions

- ~~**Which Postgres extensions are wanted at creation time?**~~ ✅ Both `pgcrypto` and
  `uuid-ossp` are installed by Supabase already, along with `pg_stat_statements` and
  `supabase_vault`. Nothing to add.
- **Does the web client keep polling, or move to Supabase Realtime?** Polling works and
  is not this spec's problem. Revisit when the Expo client lands.
