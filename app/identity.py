"""Who the caller is.

Credentials are the auth provider's problem; this module's problem is deciding
whether to believe a token it is handed, and turning a believed token into an
Account row.

Verification reads the provider's published key set rather than a shared
secret. The difference is what happens when the value leaks: a shared HS256
secret lets whoever has it mint a valid token for every user, while a public
key lets them verify tokens and nothing else. The provider signs, we check.

The key set is fetched once and remembered. Fetching per request would put the
auth provider on the critical path of every single call and take this
application down whenever it blinked. Rotation is handled by refetching when a
token arrives bearing a key id the cache has never seen — once, and then that
answer is cached too, so an unknown id is not a way to make this process hammer
the provider on demand.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

import jwt
import psycopg

from app import db

# How long a cached key set is trusted before it is refetched anyway. Rotation
# is normally noticed by the unknown-kid path; this is the backstop for the
# opposite case, where a key is withdrawn without a new one appearing.
KEY_CACHE_SECONDS = 3600.0

# How many unexplained key ids to remember before refusing to refetch for any
# more of them until the cache expires anyway. Real rotations introduce one new
# id at a time; anything past a handful is somebody probing.
MAX_UNEXPLAINED_KEYS = 32


class NotAuthenticated(Exception):
    """The caller did not prove who they are.

    One exception for every reason -- expired, forged, wrong audience,
    unparseable -- because telling a caller which of those it was tells an
    attacker which part of their token to fix.
    """


@dataclass(frozen=True)
class Account:
    id: str
    email: str | None
    display_name: str | None
    is_admin: bool


class Verifier:
    """Checks tokens against an issuer's published signing keys.

    `fetch_keys` returns a JWKS document. It is injected rather than reached
    for, so tests exercise every line of the verification with real keys and
    real signatures while replacing only the network call.
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        fetch_keys: Callable[[], dict],
        cache_seconds: float = KEY_CACHE_SECONDS,
    ):
        self._issuer = issuer
        self._audience = audience
        self._fetch_keys = fetch_keys
        self._cache_seconds = cache_seconds
        self._keys: dict[str, object] = {}
        self._fetched_at = 0.0
        # Key ids a refetch already failed to explain. Bounded, so that cycling
        # made-up ids cannot grow it without limit.
        self._unexplained: set[str | None] = set()
        # Requests are concurrent and a refetch is slow; without this, a burst
        # arriving after a rotation would each start their own.
        self._lock = threading.Lock()

    def verify(self, token: str) -> dict:
        """Return the claims of a token this issuer signed, or raise."""
        if not token:
            raise NotAuthenticated("no credential presented")
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as exc:
            raise NotAuthenticated("not a usable token") from exc

        key = self._key_for(kid)
        if key is None:
            raise NotAuthenticated("token signed by an unknown key")
        try:
            return jwt.decode(
                token,
                key=key,
                algorithms=["RS256", "ES256"],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise NotAuthenticated("that credential is not valid") from exc

    def _key_for(self, kid: str | None):
        with self._lock:
            stale = time.time() - self._fetched_at > self._cache_seconds
            if not self._keys or stale:
                self._refresh()
            if kid in self._keys:
                return self._keys[kid]

            # An id the cache has never seen is what a rotation looks like from
            # here, so refetch -- once. Remembering which ids that refetch
            # failed to explain is what stops a forged token from making this
            # process call the auth provider on every request, and it is
            # decided by what happened rather than by how long ago, so it holds
            # under a burst as well as under a slow trickle.
            if kid in self._unexplained or len(self._unexplained) >= MAX_UNEXPLAINED_KEYS:
                return None
            self._refresh()
            if kid not in self._keys:
                self._unexplained.add(kid)
            return self._keys.get(kid)

    def _refresh(self) -> None:
        document = self._fetch_keys()
        self._keys = {
            entry["kid"]: jwt.PyJWK(entry).key
            for entry in document.get("keys", [])
            if entry.get("kid")
        }
        self._fetched_at = time.time()
        # A fresh set may well explain an id that the previous one could not.
        self._unexplained.clear()


def jwks_fetcher(url: str) -> Callable[[], dict]:
    """The real network call, kept apart from everything that decides."""

    def fetch() -> dict:
        import httpx

        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json()

    return fetch


def account_for(conn: psycopg.Connection, claims: dict) -> Account:
    """The Account behind a verified token, created if this is a first visit.

    Created lazily here rather than by a trigger on the provider's user table.
    A trigger would put this logic somewhere the test suite cannot reach and the
    migrations do not own, and it would run for users this application has never
    heard from.

    The first account in an empty database is the administrator, and only while
    there is no other. Promotion after that is a deliberate SQL statement: an
    in-app "make admin" button is a privilege-escalation feature nobody asked
    for.
    """
    account_id = claims["sub"]
    row = conn.execute(
        "SELECT id, email, display_name, is_admin FROM account WHERE id = %s",
        (account_id,),
    ).fetchone()
    if row is not None:
        return Account(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            is_admin=row["is_admin"],
        )

    email = claims.get("email")
    display_name = (
        claims.get("user_metadata", {}).get("full_name")
        or claims.get("name")
        or (email.split("@")[0] if email else None)
    )
    with db.transaction(conn):
        founder = conn.execute("SELECT 1 FROM account LIMIT 1").fetchone() is None
        conn.execute(
            "INSERT INTO account (id, email, display_name, is_admin, created_at)"
            " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (account_id, email, display_name, founder, db.now()),
        )
    return Account(id=account_id, email=email, display_name=display_name, is_admin=founder)
