"""The guard in front of the API.

Credentials moved to the auth provider when the application grew accounts.
What is left here is the part that was never about credentials: deciding which
requests reach the routes at all.

Two jobs, kept separate on purpose.

The **cross-origin check** refuses a state-changing request that a browser says
came from somewhere else. It is not authentication; it is what stops another
site making a request that this application's own credentials would otherwise
authorise.

The **guard** is default-deny across the whole API surface, so an endpoint
added later is shut until somebody names it public. It sits outside the routes
rather than on each of them because the failure mode of the alternative is a
forgotten decorator on the one route that spends money.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.requests import Request

from app import db, identity

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Nothing behind `/api/` is reachable without a credential. Sign-in happens at
# the auth provider rather than here, so there is no door of our own to leave
# open -- which is why this set is empty rather than absent, and why adding to
# it should be uncomfortable.
PUBLIC_PATHS: frozenset[str] = frozenset()

# Surfaces that need the administrator role. Spend is here because it names
# every person and what they cost; maintenance because purging and taking
# backups are operator actions.
ADMIN_PREFIXES = ("/api/spend", "/api/maintenance")

API_PREFIX = "/api/"


def is_cross_origin(request: Request) -> bool:
    """Does this request appear to have been made by some other site?

    Browsers say so themselves. `Sec-Fetch-Site` is sent by every current
    browser and cannot be set by page script; `Origin` is the fallback for the
    ones that do not. A request carrying neither is not a browser cross-site
    request at all -- a command-line client sends neither -- so it is left to
    the credential check instead.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in {"same-origin", "none"}
    origin = request.headers.get("origin")
    if origin is None:
        return False
    # The scheme is deliberately not compared: behind a TLS-terminating proxy
    # the scheme we see is not the scheme the browser used.
    return urlsplit(origin).netloc.lower() != (request.headers.get("host") or "").lower()


def bearer_token(request: Request) -> str:
    """The credential, from the Authorization header and nowhere else.

    Not a cookie. The token is held by the client and sent deliberately, which
    is what makes cross-site request forgery structurally impossible rather
    than merely defended against -- another site's page cannot read this
    application's token to attach it.
    """
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


class Guard:
    """Default-deny in front of the whole API.

    Raw ASGI rather than `BaseHTTPMiddleware`: the progress stream depends on
    seeing its own client disconnect, and wrapping its receive channel is
    exactly how that gets lost.
    """

    def __init__(
        self,
        app,
        *,
        database_url: str,
        verifier: identity.Verifier,
        allowed_emails: frozenset[str] | None = None,
    ):
        self.app = app
        self._database_url = database_url
        self._verifier = verifier
        # A private build: only these verified addresses get in at all. None
        # means open — the public product; a set means a household. Checked
        # against the PROVIDER's verified email claim, before any account row
        # exists, so a stranger's sign-in leaves no trace and reaches nothing
        # that costs money.
        self._allowed_emails = allowed_emails

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

        try:
            claims = self._verifier.verify(bearer_token(request))
        except identity.NotAuthenticated:
            # One answer for every reason. Which part of a token was wrong is
            # exactly what somebody probing wants told.
            await self._refuse(401, "sign in to continue", scope, receive, send)
            return

        if self._allowed_emails is not None:
            email = str(claims.get("email") or "").strip().lower()
            if email not in self._allowed_emails:
                # Authenticated, and still not welcome: this build belongs to
                # named people. Said plainly — a 401 would send the client
                # into refresh loops for a state no refresh can fix.
                await self._refuse(
                    403, "this build is private", scope, receive, send
                )
                return

        conn = db.connect(self._database_url)
        try:
            account = identity.account_for(conn, claims)
        finally:
            conn.close()

        if request.url.path.startswith(ADMIN_PREFIXES) and not account.is_admin:
            await self._refuse(403, "this needs an administrator", scope, receive, send)
            return

        # What the request is allowed to act as, established once and read back
        # by the routes as the identity every job is recorded against.
        scope.setdefault("state", {})["account"] = account
        await self.app(scope, receive, send)

    async def _refuse(self, status: int, detail: str, scope, receive, send) -> None:
        await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)
