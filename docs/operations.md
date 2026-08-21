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
attribution is what per-person Invite Tokens are for. Defaults: $25 per person
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
curl -X POST -H "x-owner-token: $AI_ANKI_OWNER_TOKEN" \
  https://<app>/api/maintenance/purge -d '{"older_than_days": 30}'
```

## Backups

Platform volume snapshots are documented as **not** being a backup. The database
is the one thing whose loss cannot be recovered by re-running anything, so it is
copied off the platform on a schedule.

```bash
curl -X POST -H "x-owner-token: $AI_ANKI_OWNER_TOKEN" \
  https://<app>/api/maintenance/backup
```

`VACUUM INTO` takes its own read transaction, so the copy is a coherent
point-in-time image. A plain file copy of a WAL-mode database is not.

## Owner credential

`AI_ANKI_OWNER_TOKEN` is a runtime secret. Unset means nobody is the owner,
which **closes** minting rather than opening it.

Minting invites, revoking them, viewing spend, purging and backups are all owner
surfaces, reached with `x-owner-token` rather than a session.
