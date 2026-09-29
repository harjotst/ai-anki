# 04 — Invite tokens & sessions

**What to build:** Access control. Each person gets their own revocable invite link rather than everyone sharing one password, so a leak is revocable without a rotation and spend becomes attributable per person — which ticket 17 depends on.

**Blocked by:** 01 — Walking skeleton

**Status:** done — 13 access-control tests green

> Note: token comparison (AC 4) is constant-time by construction — `hmac.compare_digest`
> over fixed-length digests in `auth._same` and `auth.redeem`. It is verified by reading,
> not by a timing test, which would be flaky and prove little.
>
> A defect was found and fixed while completing this ticket: `redeem` compared the stored
> secret hash through `_same`, which digests both sides, so it tested
> `digest(secret) == digest(digest(secret))` and NO invite could ever be redeemed.

- [x] The owner can mint a per-person invite token and revoke one without affecting anyone else
- [x] Redeeming an invite creates an opaque 128-bit session identifier stored in SQLite with an absolute expiry
- [x] The session cookie is HttpOnly, Secure, SameSite=Lax and scoped to the root path
- [x] Token comparison is constant-time
- [x] Login attempts are rate limited per IP with lockout and a fixed delay on failure, backed by the same database
- [x] Every mutating endpoint rejects requests that fail a same-origin check
- [x] Truncating the sessions table logs everyone out
- [x] Every job records which invite token created it
