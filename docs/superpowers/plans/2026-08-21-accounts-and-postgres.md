# Accounts and Postgres Implementation Plan

> **Status as of 2026-08-21: tasks 1–10 done and merged.** Task 5 was withdrawn
> during implementation — see below. Task 11's code is written and the frontend
> builds; the two verifications it names still need a real Supabase project and
> are the only part of this spec that is not finished.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SQLite with managed Postgres and owner-minted Invite Tokens with real accounts, changing nothing about how documents become decks.

**Architecture:** The datastore moves first (tasks 1–5), then identity (tasks 6–9). Every task ends with the full suite green. The 219 existing tests drive HTTP rather than SQL, so they are the specification of "generation still works"; a test that needs rewriting is a test that was coupled to SQLite, and that coupling is the defect.

**Tech Stack:** psycopg 3, testcontainers-python, Postgres 16, Supabase Auth (JWKS), PyJWT, FastAPI.

## Global Constraints

- **The generation pipeline does not change.** No edits to prompts, JSON schemas, cache lifetimes, or the worker's pacesetter-then-fan-out shape.
- **Placeholders become `%s`, not a translation layer.** All 203 `?` placeholders are rewritten. A wrapper that rewrites `?` at runtime breaks on `?` inside string literals, JSON operators and LIKE patterns.
- **`row["column"]` access is preserved** via `psycopg.rows.dict_row`. 95 call sites depend on it and none need to change.
- **Every timestamp column becomes `TIMESTAMPTZ`.** No floats, no naive datetimes, no `datetime('now')` strings.
- **No task may leave the suite red.** Tasks 1–2 run both backends; after task 3 only Postgres.
- **Access-control tests are ported, never rewritten.** They are the only thing standing between one person's decks and another's.

---

### Task 1: Postgres fixture alongside SQLite

**Files:**
- Create: `app/db_pg.py`
- Modify: `tests/conftest.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `db_pg.connect(dsn: str) -> psycopg.Connection`, `db_pg.transaction(conn)`, `db_pg.initialise(dsn: str) -> None`
- Produces: a `backend` pytest fixture parameterised over `("sqlite", "postgres")`

- [ ] **Step 1: Add dependencies**

```toml
dev = [
    "psycopg[binary]>=3.2",
    "testcontainers[postgres]>=4.8",
]
```

- [ ] **Step 2: Write the failing test**

```python
def test_the_same_schema_initialises_on_postgres(pg_dsn):
    db_pg.initialise(pg_dsn)
    conn = db_pg.connect(pg_dsn)
    tables = {r["table_name"] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
    ).fetchall()}
    assert {"deck", "job", "source", "topic", "card"} <= tables
```

- [ ] **Step 3: Run it and watch it fail** — `pytest tests/test_postgres_harness.py -v`, expect `ModuleNotFoundError: app.db_pg`.

- [ ] **Step 4: Add the session-scoped container fixture**

One container per session; a fresh schema per test, because a rollback fixture breaks every test whose code commits — which is every worker test.

```python
@pytest.fixture(scope="session")
def pg_container():
    from testcontainers.postgres import PostgresContainer
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg

@pytest.fixture
def pg_dsn(pg_container, request):
    schema = "t_" + uuid.uuid4().hex[:16]
    dsn = pg_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    admin = psycopg.connect(dsn, autocommit=True)
    admin.execute(f'CREATE SCHEMA "{schema}"')
    yield f"{dsn}?options=-csearch_path%3D{schema}"
    admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
    admin.close()
```

- [ ] **Step 5: Write `app/db_pg.py` with the ported schema** — `SCHEMA_PG`, plus `connect`, `transaction`, `initialise`. Conversions per the spec's table.

- [ ] **Step 6: Run the test** — expect PASS.

- [ ] **Step 7: Commit** — `git commit -m "A Postgres schema and a container fixture, beside SQLite"`

---

### Task 2: Port the SQL

**Files:** `app/jobs.py`, `app/ledger.py`, `app/auth.py`, `app/budget.py`, `app/dedup.py`, `app/progress.py`

**Interfaces:** Consumes task 1's `db_pg`. Produces no new names — every function keeps its signature.

- [ ] **Step 1: Rewrite placeholders** — `?` → `%s` across all six modules. 203 sites, mechanical.
- [ ] **Step 2: Replace `INSERT OR REPLACE`** with `INSERT … ON CONFLICT (cols) DO UPDATE SET …`.
- [ ] **Step 3: Replace the 5 `lastrowid` uses** with `RETURNING id`.
- [ ] **Step 4: Audit every timestamp.** `time.time()` writes become `datetime.now(timezone.utc)`; comparisons in Python that assumed floats become datetime comparisons. This is the step where a silent bug hides — check each of the 19 sites.
- [ ] **Step 5: Run the whole suite against Postgres** — `pytest -q`, both backends green.
- [ ] **Step 6: Commit** — `git commit -m "Port the SQL to Postgres paramstyle and timestamps"`

---

### Task 3: Delete SQLite

**Files:** Delete `app/db.py`'s SQLite half; rename `app/db_pg.py` → `app/db.py`; `tests/conftest.py`.

- [ ] **Step 1: Drop the backend parameterisation** from conftest.
- [ ] **Step 2: Delete** `PRAGMA` calls, `MIGRATIONS`, `_migrate`, `backup_to`, `BEGIN IMMEDIATE`.
- [ ] **Step 3: Run the suite** — expect green on Postgres only.
- [ ] **Step 4: Commit** — `git commit -m "Delete the SQLite backend"`

---

### Task 4: Migrations tool

**Files:** Create `migrations/`, modify `app/db.py`, `pyproject.toml`.

Alembic. The hand-rolled `MIGRATIONS` list added on 2026-08-21 was correct for one machine with no downtime window, and cannot express a rename, a backfill or a rollback — all of which tasks 7–8 need.

- [ ] **Step 1: `alembic init migrations`, point it at the app's DSN.**
- [ ] **Step 2: Autogenerate the baseline** from the current schema; assert it produces an empty diff against a fresh database.
- [ ] **Step 3: Boot runs `alembic upgrade head`** instead of `initialise`.
- [ ] **Step 4: Run the suite.** - [ ] **Step 5: Commit.**

---

### Task 5: ~~Simplify the worker~~ — WITHDRAWN

The spec's claim that `FOR UPDATE SKIP LOCKED` replaces `worker_id` was wrong.
`SKIP LOCKED` pulls work off a queue; this application has no queue, because a
job runs in the process that received its HTTP request. `worker_id` and
`recover_orphans` solve a different problem — an in-flight job with no live
process — and solve it correctly for the one machine this spec deploys.

The multi-machine answer is a lease with a heartbeat. It buys nothing until
there is a second machine. Not built.

See the spec's "The worker" section for the full correction.

---

### Task 6: JWT verification against a fake JWKS

**Files:** Create `app/identity.py`, `tests/test_identity.py`; modify `tests/conftest.py`.

**Interfaces:**
- Produces: `identity.verify(token: str, jwks_url: str) -> dict` (returns claims), `identity.Account`, and the FastAPI dependency `account_of`.

The seam is the JWKS *network fetch*, matching how `ClaudeScript` fakes only the Anthropic transport. Tests generate a real RSA keypair, serve it as a real JWKS document, and sign real tokens. Nothing about the verification logic is stubbed.

- [ ] **Step 1: Write the failing tests** — a valid token resolves an account; an expired one is 401; one signed by the wrong key is 401; one with the wrong `aud` is 401; an unknown `kid` triggers exactly one JWKS refetch.
- [ ] **Step 2: Run them, watch them fail.**
- [ ] **Step 3: Implement `identity.verify`** with PyJWT and a bounded-TTL JWKS cache that refetches on unknown `kid`.
- [ ] **Step 4: Run the tests.** - [ ] **Step 5: Commit.**

---

### Task 7: The `account` table and `account_of`

**Files:** `migrations/`, `app/identity.py`, `app/main.py`, `tests/test_accounts.py`

- [ ] **Step 1: Write the failing tests** — first authenticated request creates exactly one `account`; a second request creates none; the first account in an empty database is admin; the second is not.
- [ ] **Step 2: Run them, watch them fail.**
- [ ] **Step 3: Add the migration** — `account(id UUID PK, display_name TEXT, is_admin BOOL, created_at TIMESTAMPTZ, signup_source TEXT)`.
- [ ] **Step 4: Implement lazy creation** in `account_of`. Not a database trigger: a trigger puts application logic where the test suite cannot reach it and Alembic does not own it.
- [ ] **Step 5: Run the suite.** - [ ] **Step 6: Commit.**

---

### Task 8: Move ownership to `account_id`

**Files:** `migrations/`, `app/jobs.py`, `app/ledger.py`, `app/budget.py`, `app/main.py`, `tests/test_access_control.py`

- [ ] **Step 1: Port the access-control tests** to accounts. Every one that asserted "Bob cannot see Alice's job" must still assert it. These are ported, not rewritten.
- [ ] **Step 2: Run them, watch them fail.**
- [ ] **Step 3: Migration** — add `account_id UUID REFERENCES account(id)` to `job` and `deck`; no backfill, existing rows are test data.
- [ ] **Step 4: Switch all scoping queries.** Grep for `invite_id`; every hit becomes `account_id` or is deleted.
- [ ] **Step 5: Run the suite.** - [ ] **Step 6: Commit.**

---

### Task 9: Delete invites and the owner token

**Files:** Delete most of `app/auth.py`; modify `app/main.py`, `app/asgi.py`, `tests/`, `docs/operations.md`

- [ ] **Step 1: Delete** `mint_invite`, `redeem`, `list_invites`, `revoke_invite`, the session table, the login-failure lockout, `SESSION_COOKIE`, `x-owner-token`.
- [ ] **Step 2: Move admin surfaces** onto `account.is_admin`.
- [ ] **Step 3: Assert `x-owner-token` appears nowhere** — `grep -r "owner_token" app/ tests/` returns nothing.
- [ ] **Step 4: Update `docs/operations.md`.** - [ ] **Step 5: Run the suite.** - [ ] **Step 6: Commit.**

---

### Task 10: Retarget the backup to `pg_dump`

**Files:** `app/backup.py`, `tests/test_backup.py`

- [ ] **Step 1: Change the failing test** — `snapshot()` produces a restorable custom-format dump.
- [ ] **Step 2: Run it, watch it fail.**
- [ ] **Step 3: Implement** `pg_dump --format=custom`. Upload, date-sorted keys, 14-day retention and listing-driven pruning are unchanged, as are their tests.
- [ ] **Step 4: Run the suite.** - [ ] **Step 5: Commit.**

---

### Task 11: Wire the web client to Supabase Auth

**Files:** `frontend/src/App.jsx`, `frontend/package.json`, `docs/operations.md`

**Blocked on the user:** needs a real Supabase project — URL and anon key.

- [ ] **Step 1: Add `@supabase/supabase-js`.**
- [ ] **Step 2: Replace `SignIn`'s token box** with Google and Apple buttons.
- [ ] **Step 3: Attach the bearer token** to every `api()` call; delete the cookie path.
- [ ] **Step 4: Verify account linking against the real project** — sign in with Google, sign out, sign in with Apple on the same address, assert one `account` row. This is success criterion 2 and the spec's largest unverified assumption.
- [ ] **Step 5: Verify the JWKS assumption** marked ⚠️ in the spec: asymmetric keys by default, and the endpoint path. If only HS256 is available, record why in the spec.
- [ ] **Step 6: Commit.**

---

## Self-review

**Spec coverage:** identity → 6, 7; JWT → 6; admin → 7, 9; ownership columns → 8; schema port → 1, 2; migrations tool → 4; worker → 5; backups → 10; test harness → 1. All nine of the spec's "order of work" items map to a task.

**Placeholders:** none. Task 2's "203 sites, mechanical" is a real instruction, not a deferral — the conversions are enumerated in Global Constraints.

**Type consistency:** `account_of` is named identically in tasks 6, 7 and 8. `db_pg.connect/transaction/initialise` in task 1 match their use in 2 and 3.

**Known gap:** tasks 1–10 are executable without any vendor. Task 11 alone needs the Supabase project, so it is last and marked blocked.
