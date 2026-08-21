"""Access control: Invite Tokens, sessions, and the guard in front of the API.

Access is per-person by design. One shared password cannot be revoked without
rotating it for everybody, and it leaves spend unattributable — so the
credential is an Invite Token the owner mints for one person and can revoke on
its own, which is what ticket 17 later hangs a budget off.

Nothing here stores a credential it could hand back. An Invite Token is shown
once, at minting, and only its digest is kept; session ids are stored the same
way. A copy of the database is therefore not a set of working logins.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.requests import Request

from app import db

SESSION_COOKIE = "ai_anki_session"

# 128 bits of entropy, which is the whole of the credential: the id is opaque
# and carries nothing, so nothing about it can be forged or read.
SESSION_ID_BYTES = 16
INVITE_SECRET_BYTES = 32

# Absolute, never extended by use: a stolen cookie has a bounded life whatever
# the thief does with it.
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60

# Five tries per quarter of an hour, per address. The thing being guessed is
# 256 bits of randomness, so the limit is not really about the guessing — it is
# about the request rate a stranger who found the hostname can put through.
MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 15 * 60.0
FAILED_LOGIN_DELAY_SECONDS = 0.5

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The only door that can be knocked on without a credential, because it is the
# one that hands them out.
PUBLIC_PATHS = frozenset({"/api/session"})
# Minting and revoking are the owner's, and are reached with the owner's own
# credential rather than with a session.
# Owner-only surfaces. Spend is here because it names every person and what
# they cost; maintenance because purging and backups are operator actions.
OWNER_PREFIXES = ("/api/invites", "/api/spend", "/api/maintenance")
OWNER_PREFIX = "/api/invites"
API_PREFIX = "/api/"


class InvalidToken(Exception):
    """The presented Invite Token is not one we would let in."""


@dataclass(frozen=True)
class Invite:
    invite_id: str
    person: str
    revoked: bool
    created_at: float


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def _same(presented: str, expected: str) -> bool:
    """Compare two credentials without leaking how far they matched.

    Both sides are digested first, so the comparison is over fixed-length ASCII
    and the length of the presented value tells an attacker nothing either.
    """
    return hmac.compare_digest(_digest(presented), _digest(expected))


def is_owner(presented: str | None, owner_token: str | None) -> bool:
    # An unconfigured owner token is not a blank one that anybody can match: it
    # closes the door.
    if not owner_token or not presented:
        return False
    return _same(presented, owner_token)


def mint_invite(conn: sqlite3.Connection, person: str, *, now: float | None = None) -> str:
    """Issue one person's Invite Token, returning it the only time it exists.

    The token is `<invite_id>.<secret>`. The id half is not a secret and is what
    the row is found by, so redeeming never has to search on the secret half.
    """
    now = time.time() if now is None else now
    invite_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(INVITE_SECRET_BYTES)
    conn.execute(
        "INSERT INTO invite (id, person, secret_hash, created_at) VALUES (?, ?, ?, ?)",
        (invite_id, person, _digest(secret), now),
    )
    return f"{invite_id}.{secret}"


def list_invites(conn: sqlite3.Connection) -> list[Invite]:
    rows = conn.execute(
        "SELECT id, person, revoked_at, created_at FROM invite ORDER BY created_at, id"
    ).fetchall()
    return [
        Invite(
            invite_id=row["id"],
            person=row["person"],
            revoked=row["revoked_at"] is not None,
            created_at=row["created_at"],
        )
        for row in rows
    ]


def revoke_invite(conn: sqlite3.Connection, invite_id: str, *, now: float | None = None) -> bool:
    """Withdraw one person's access, and only that person's.

    Their live sessions go with the invite. Leaving them would make revocation
    mean "no new logins", which is not what someone reaching for it after a leak
    is asking for.
    """
    now = time.time() if now is None else now
    if conn.execute("SELECT id FROM invite WHERE id = ?", (invite_id,)).fetchone() is None:
        return False
    with db.transaction(conn):
        conn.execute(
            "UPDATE invite SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (now, invite_id),
        )
        conn.execute("DELETE FROM session WHERE invite_id = ?", (invite_id,))
    return True


def redeem(
    conn: sqlite3.Connection,
    token: str,
    *,
    ttl_seconds: float,
    now: float | None = None,
) -> tuple[str, str]:
    """Exchange an Invite Token for a session, returning `(session_id, person)`.

    A token that names no invite and a token whose secret is wrong fail the same
    way, at the same cost: the digest comparison runs against a stand-in when
    there is no row, so neither the shape of the answer nor the work done to
    reach it says which of the two happened.
    """
    now = time.time() if now is None else now
    invite_id, _, secret = (token or "").partition(".")
    row = conn.execute(
        "SELECT id, person, secret_hash FROM invite WHERE id = ? AND revoked_at IS NULL",
        (invite_id,),
    ).fetchone()
    # The stored side is already a digest, so it is compared as-is against one
    # digest of the presented secret. Passing it through `_same` would digest it
    # a second time and no correct token could ever match.
    expected_hash = row["secret_hash"] if row is not None else _digest("")
    matched = hmac.compare_digest(_digest(secret), expected_hash)
    if row is None or not matched:
        raise InvalidToken("that invite link is not valid")

    session_id = secrets.token_hex(SESSION_ID_BYTES)
    conn.execute(
        "INSERT INTO session (id_hash, invite_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_digest(session_id), row["id"], now, now + ttl_seconds),
    )
    return session_id, row["person"]


def session_invite(
    conn: sqlite3.Connection, session_id: str | None, *, now: float | None = None
) -> str | None:
    """The Invite Token behind a session cookie, if it is still good for one.

    The invite is joined rather than trusted: revoking has to take effect on the
    next request, not on the next login.
    """
    if not session_id:
        return None
    now = time.time() if now is None else now
    row = conn.execute(
        "SELECT s.invite_id FROM session s JOIN invite i ON i.id = s.invite_id"
        " WHERE s.id_hash = ? AND s.expires_at > ? AND i.revoked_at IS NULL",
        (_digest(session_id), now),
    ).fetchone()
    return row["invite_id"] if row is not None else None


def record_failure(conn: sqlite3.Connection, address: str, *, now: float | None = None) -> None:
    conn.execute(
        "INSERT INTO login_failure (address, failed_at) VALUES (?, ?)",
        (address, time.time() if now is None else now),
    )


def clear_failures(conn: sqlite3.Connection, address: str) -> None:
    conn.execute("DELETE FROM login_failure WHERE address = ?", (address,))


def lockout_remaining(
    conn: sqlite3.Connection,
    address: str,
    *,
    lockout_seconds: float = LOCKOUT_SECONDS,
    max_failures: int = MAX_FAILED_LOGINS,
    now: float | None = None,
) -> float:
    """How long this address must wait, in seconds; zero if it may try now.

    The count lives in the database with everything else, because a lockout held
    in memory is lifted by the restart an attacker can cause for free.
    """
    now = time.time() if now is None else now
    row = conn.execute(
        "SELECT COUNT(*) AS failures, MAX(failed_at) AS last FROM login_failure"
        " WHERE address = ? AND failed_at > ?",
        (address, now - lockout_seconds),
    ).fetchone()
    if row["failures"] < max_failures:
        return 0.0
    return max(0.0, row["last"] + lockout_seconds - now)


def is_cross_origin(request: Request) -> bool:
    """Does this request look like it was made by some other site?

    Browsers say so themselves. `Sec-Fetch-Site` is sent by every current
    browser and cannot be set by page script; `Origin` is the fallback for the
    ones that do not. A request carrying neither is not a browser cross-site
    request at all — a command-line client sends neither — so it is left to the
    credential check instead.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in {"same-origin", "none"}
    origin = request.headers.get("origin")
    if origin is None:
        return False
    # The scheme is deliberately not compared. The session cookie is `Secure`,
    # so no plain-http origin can be carrying one, and behind a TLS-terminating
    # proxy the scheme we see is not the scheme the browser used.
    return urlsplit(origin).netloc.lower() != (request.headers.get("host") or "").lower()


class Guard:
    """Default-deny in front of the whole API.

    It sits outside the routes rather than on each of them so that "is this
    endpoint protected?" has one answer for the whole application: an endpoint
    added later is shut until it is named public here. That is worth the
    slightly awkward shape, because the failure mode of the alternative is a
    forgotten decorator on the one route that spends money.

    Raw ASGI rather than `BaseHTTPMiddleware`: the progress stream depends on
    seeing its own client disconnect, and wrapping its receive channel is
    exactly how that gets lost.
    """

    def __init__(self, app, *, db_path: Path, owner_token: str | None):
        self.app = app
        self._db_path = Path(db_path)
        self._owner_token = owner_token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if request.method not in SAFE_METHODS and is_cross_origin(request):
            await self._refuse(
                403, "this request did not come from the application", scope, receive, send
            )
            return
        if request.url.path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        conn = db.connect(self._db_path)
        try:
            if request.url.path.startswith(OWNER_PREFIXES):
                if not is_owner(request.headers.get("x-owner-token"), self._owner_token):
                    await self._refuse(401, "this needs the owner credential", scope, receive, send)
                    return
                invite_id = None
            else:
                invite_id = session_invite(conn, request.cookies.get(SESSION_COOKIE))
                if invite_id is None:
                    await self._refuse(401, "sign in with your invite link", scope, receive, send)
                    return
        finally:
            conn.close()

        # What the request is allowed to act as, established once and read back
        # by the routes as the identity every job is recorded against.
        scope.setdefault("state", {})["invite_id"] = invite_id
        await self.app(scope, receive, send)

    async def _refuse(self, status: int, detail: str, scope, receive, send) -> None:
        await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)
