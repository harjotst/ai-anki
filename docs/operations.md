# Operations

## Spend controls

Four layers, from outermost to innermost. The order matters: only the first
survives a bug in this application.

### 1. The provider-side monthly cap — the outer backstop

Set a hard monthly spend limit and a low-balance alert on the Anthropic
organisation, in the Console. **This is the only control that survives a bug in
this application**, and it is the reason it exists: every other layer below is
code, and code is what you are protecting yourself against.

It is a backstop, not a control. When it trips it stops everybody at once, with
no message, no attribution, and no way to tell whose job did it. The layers
below exist so it should never be the thing that stops you.

### 2. Per-job token ceiling

Measured at admission with `count_tokens` over the exact assembled request, and
**re-checked before the generation fan-out** — a plan multiplies the work, and
the sources can grow between the two passes. Default 700,000 input tokens, which
leaves headroom inside the 1M context for the plan, the cards and the thinking
that produces them.

A job over the ceiling is refused before a single generation call. It costs one
token count and nothing else.

### 3. Rolling 24-hour budgets

Per person and global, both computed from **recorded usage** rather than
estimates — `api_call` rows carry what the API itself reported. Per-person
attribution is what recording an account against every job is for. Defaults: $25 per person
per day, $100 globally.

The window rolls rather than resetting at midnight, so a spent budget frees up
gradually as older jobs age out.

### 4. Kill switch

```bash
fly secrets set --stage AI_ANKI_GENERATION_DISABLED=1
```

Read at call time, never cached, so it takes effect without a redeploy. Set it
and no new generation starts; unset it and work resumes.

Use `--stage` unless you want every machine to restart immediately — a plain
`fly secrets set` restarts them, which kills any job in flight.

## Retention

Split by data class, deliberately:

- **Uploaded sources and generated packages** are purged on a schedule. They are
  the bulk of the disk and the part with a copyright and privacy cost to
  holding.
- **The Card Ledger is never purged.** It is a few hundred bytes per card, and
  losing it means every later regeneration hands the user a second copy of their
  own deck instead of updating it. This is the single most destructive thing the
  system could do, and the only thing preventing it is that these rows still
  exist.

```bash
curl -X POST -H "authorization: Bearer $TOKEN" \
  https://<app>/api/maintenance/purge -d '{"older_than_days": 30}'
```

## Backups

Platform volume snapshots are documented as **not** being a backup. The database
is the one thing whose loss cannot be recovered by re-running anything — every
card identity lives in it, and without them a re-import hands the user a second
copy of their whole deck instead of updating it — so it is copied off the
platform every night.

`VACUUM INTO` takes its own read transaction, so the copy is a coherent
point-in-time image. A plain file copy of a WAL-mode database is not.

### Setting it up

```bash
fly storage create --name ai-anki-backups
```

That sets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_ENDPOINT_URL_S3`
as secrets on the app. One more is needed, because the presence of a bucket name
is what turns backups on:

```bash
fly secrets set AI_ANKI_BACKUP_BUCKET=ai-anki-backups
```

With no bucket set, backups are **off rather than broken**. That is deliberate:
local development and a first deploy both run without one, and a nightly task
that raises every night is a task whose alarms get muted.

### What runs

A task inside the application wakes at 03:00 UTC, takes a `VACUUM INTO`
snapshot, gzips it, uploads it under a date-sorted key, and deletes anything
older than 14 days. Every failure is logged and slept off rather than raised: a
backup task that takes the process down converts "last night's copy is missing"
into "the service is down".

Pruning is driven by what the bucket listing reports, never by parsing key
names. A key that failed to parse would otherwise be kept for ever or, far
worse, treated as ancient and deleted.

Trigger one by hand at any time:

```bash
curl -X POST -H "authorization: Bearer $TOKEN" \
  https://<app>/api/maintenance/backup
```

### Restoring

```bash
aws s3 ls s3://ai-anki-backups/db/ --endpoint-url https://fly.storage.tigris.dev
```

```bash
aws s3 cp s3://ai-anki-backups/db/<key> ./restore.dump \
  --endpoint-url https://fly.storage.tigris.dev
```

```bash
pg_restore --dbname "$AI_ANKI_DATABASE_URL" --no-owner --clean --if-exists ./restore.dump
```

**Use a `pg_restore` whose major version matches the target server.** Verified
on 2026-08-21: a dump taken with client 17 restores its data correctly into a
16 server, but `pg_restore` 17 emits `SET transaction_timeout = 0`, which 16
does not recognise — so every row lands and the command still exits non-zero.
An automated restore that trusts the exit code would report a working restore
as a failure, or a failed one as working, depending on which way it guessed.

The image carries client 17 because `pg_dump` refuses outright to dump a server
newer than itself; Debian's own package is 15 and cannot back up a modern
server at all. The rule is one-directional: the client must be at least as new
as the server it dumps.

Test a restore before you need one. A backup nobody has restored is a backup
whose format nobody has checked.

## Administrators

Sign-in belongs to Supabase. This application holds no credentials at all, so a
copy of its database is not a set of working logins.

Administration is a role on an account rather than a second credential carried
separately. `/api/spend`, `/api/maintenance/purge` and `/api/maintenance/backup`
need `account.is_admin`; every other API surface needs only a valid token.

**The first account created in an empty database becomes the administrator**,
and only while there is no other. That makes a fresh deployment usable without
seeding anything — sign in once, and you are it.

Every promotion after that is a deliberate SQL statement:

```sql
UPDATE account SET is_admin = true WHERE email = 'someone@example.com';
```

An in-app "make admin" surface is deliberately absent. It is a
privilege-escalation feature nobody asked for.

To call an admin endpoint by hand, take the access token from the browser —
your Supabase session is in local storage — and send it as
`authorization: Bearer <token>`.

## Auth

Supabase Auth issues the token; this application only decides whether to believe it.

**Verified against the live project on 2026-08-22:**

| | |
|---|---|
| Issuer | `https://<project>.supabase.co/auth/v1` |
| JWKS | `{issuer}/.well-known/jwks.json` |
| Algorithm | **ES256** (elliptic curve) |
| Audience | `authenticated` |

The key is asymmetric, which is the property worth having: a leaked shared secret would
mint valid tokens for every user, while the published key verifies tokens and mints
nothing. `app/identity.py` builds the JWKS URL from the issuer, so `AI_ANKI_JWKS_URL`
only needs setting if that ever stops being true.

The key set is fetched once and cached. A token bearing an unfamiliar `kid` triggers one
refetch — that is how rotation is noticed without a deploy — and the ids that refetch
failed to explain are remembered, so a forged token cannot make the process call the auth
provider on every request.

```bash
fly secrets set AI_ANKI_JWT_ISSUER=https://<project>.supabase.co/auth/v1
```

### Turning the providers on

In Google Cloud — APIs & Services → OAuth consent screen, then Credentials → OAuth
client ID → **Web application**. The one field that has to be exact:

```
https://<project>.supabase.co/auth/v1/callback
```

Paste the client id and secret into Supabase → Authentication → Providers → Google.

Two settings there, and both answers follow from how this application works:

- **Skip nonce checks: off.** The nonce is what stops a stolen id token being replayed.
  It only needs skipping when a native SDK cannot send one, and web OAuth always can.
- **Allow users without an email: off.** An account is keyed on the subject claim, but
  the *display* name and every "who is this" surface falls back to the email. More
  importantly, somebody with no address has no way to be found or recognised.

Supabase → Authentication → URL Configuration also needs every origin the application is
served from in the redirect allow list, including `http://localhost:8080` for local work.
A missing entry fails at the end of the round trip, after the person has already signed
in, which reads as the application being broken rather than misconfigured.

### Two sign-in methods, one account

Automatic account linking matches a **verified email**. Apple's "Hide My Email" hands
over a private relay address instead of the real one, so somebody who used Google first
and Apple second arrives as a *second account* with none of their decks in it.

That is Apple's design rather than something to fix, so the application does not rely on
automatic matching: the "How you sign in" screen attaches a second method deliberately.
The last remaining method cannot be detached, because an account with no way to sign into
it is an account nobody can reach.

## Deploying

One machine, one volume, one region. Two machines would be two different
SQLite databases, silently — which is why `min_machines_running` is 1 and
`auto_stop_machines` is off. A job runs for minutes after its request has
returned, so auto-stopping on idle HTTP would kill runs part-way through.

### First deploy

```bash
fly launch --no-deploy --copy-config --name ai-anki --region lhr
```

```bash
fly volumes create ai_anki_data --region lhr --size 3
```

The volume holds uploads and `TMPDIR` only. The database is Supabase's now,
which is why losing this volume costs a re-upload rather than everything.

```bash
fly secrets set ANTHROPIC_API_KEY=sk-ant-... \
  AI_ANKI_DATABASE_URL="postgresql://..." \
  AI_ANKI_JWT_ISSUER="https://<project>.supabase.co/auth/v1"
```

The database URL and the issuer both come from the Supabase project. The
frontend needs its own two, at build time rather than run time, because Vite
inlines them:

```bash
fly secrets set VITE_SUPABASE_URL="https://<project>.supabase.co" VITE_SUPABASE_ANON_KEY="<anon key>"
```

```bash
fly deploy
```

Then open the app and sign in with Google. Being the first account in an empty
database makes you the administrator; nothing needs seeding.

### Every deploy after that

`fly deploy` SIGTERMs the running machine. That is a normal event here rather
than an exceptional one: the drain stops taking new work, gives calls already
in flight a bounded window to land, and checkpoints where it got to. A job
caught by a deploy comes back as `interrupted` and resumes on the next run
rather than restarting from nothing.

Schema changes ride along with the deploy. `db.MIGRATIONS` is applied at boot,
additively — `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
exists, so a new column has to be added explicitly or a live volume keeps the
old shape for ever.

### Sizing

The volume holds the database, the uploads and `TMPDIR`. Uploads dominate and
are purged on a schedule; 3GB is comfortable for a term's material for a handful
of people. One LibreOffice conversion peaks around 218MB, measured, which is why
the machine is 1GB rather than 256MB.
