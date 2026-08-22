import json
import threading
import time
import uuid as _uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from app import identity
from app.main import create_app

# --- who the tests are signed in as --------------------------------------
#
# Real RSA keys, real JWTs, real verification. Only the JWKS *fetch* is
# replaced, which is the same seam `ClaudeScript` uses for the Anthropic
# transport: the application's own auth code runs in full, so a mistake in it
# fails here rather than in front of somebody's decks.

ISSUER = "https://project.test.supabase.co/auth/v1"
AUDIENCE = "authenticated"


class Identities:
    """A signing key, and accounts that can prove who they are with it."""

    def __init__(self):
        self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "test-key"

    def jwks(self) -> dict:
        return {
            "keys": [
                {
                    **jwt.algorithms.RSAAlgorithm.to_jwk(
                        self._private.public_key(), as_dict=True
                    ),
                    "kid": self.kid,
                    "use": "sig",
                    "alg": "RS256",
                }
            ]
        }

    def token(self, account_id: str, *, email: str | None = None, name: str | None = None) -> str:
        issued = int(time.time())
        claims = {
            "sub": account_id,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": issued,
            "exp": issued + 3600,
        }
        if email:
            claims["email"] = email
        if name:
            claims["user_metadata"] = {"full_name": name}
        return jwt.encode(claims, self._private, algorithm="RS256", headers={"kid": self.kid})

    def verifier(self):
        return identity.Verifier(issuer=ISSUER, audience=AUDIENCE, fetch_keys=self.jwks)


# The default persona. `ADMIN` is simply whoever arrives first in an empty
# database, which is what the application does in production too.
TESTER = "00000000-0000-0000-0000-000000000001"
SOMEBODY_ELSE = "00000000-0000-0000-0000-000000000002"


def account_id(seed: int) -> str:
    """A stable, valid UUID per test persona. Supabase ids are UUIDs and the
    column is typed as one, so a bare string would pass here and fail there."""
    return str(_uuid.UUID(int=seed))


def bearer(token: str) -> dict:
    return {"authorization": f"Bearer {token}"}


def _multipart_filename(body: bytes) -> str | None:
    """Pull the filename out of a multipart upload without a parser."""
    marker = b'filename="'
    start = body.find(marker)
    if start == -1:
        return None
    start += len(marker)
    return body[start : body.find(b'"', start)].decode("utf-8", "replace")


class MachineKilled(BaseException):
    """The machine went away mid-call.

    It stands in for a SIGKILL, and being a `BaseException` is what makes it
    faithful: the Anthropic SDK turns any `Exception` from the transport into an
    `APIConnectionError` and retries it, which is the opposite of a machine
    dying. Nothing recovers from this one — the process that hits it is
    finished, so whatever a job knows afterwards it committed beforehand.
    """


_KILLED = object()


class ClaudeScript:
    """A scripted Anthropic API, faked at the network transport only.

    The real SDK stays in the loop — only the HTTP boundary is replaced — so SDK
    misuse still fails tests and the application needs no test-only seam of its
    own. Tests queue response bodies; requests are recorded for assertions.
    """

    def __init__(self):
        self._queued: list[tuple[object, float]] = []
        self.requests: list[dict] = []
        # The admission gate and the Files API are separate endpoints; keeping
        # their traffic apart is what lets a test say "nothing was generated".
        self.count_requests: list[dict] = []
        self.file_requests: list[httpx.Request] = []
        self._token_counts: list[int] = []
        self._uploads: list[str] = []
        self._paused = threading.Event()
        # How many message calls are in flight at once, and the high-water mark.
        # This is what lets a test assert the SHAPE of the fan-out rather than
        # its wall-clock, which would be flaky.
        self._in_flight = 0
        self.peak_in_flight = 0
        self.overlapped_with_first = False
        self._lock = threading.Lock()

    def replies(
        self,
        text: str,
        *,
        stop_reason: str = "end_turn",
        usage: dict | None = None,
        pause: float = 0.0,
    ):
        """Queue a normal assistant reply whose single text block is `text`.

        `pause` holds the call open, the way a real topic call does for minutes
        at a time — long enough for something else to happen to the machine
        while it is waiting.
        """
        self._queue(
            {
                "id": f"msg_{len(self._queued)}",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [{"type": "text", "text": text}],
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    **(usage or {}),
                },
            },
            pause,
        )
        return self

    def replies_json(self, payload: dict, **kwargs):
        return self.replies(json.dumps(payload), **kwargs)

    def refuses(self, category: str = "bio"):
        """Queue a safety refusal — HTTP 200, empty content, no text block."""
        self._queue(
            {
                "id": f"msg_{len(self._queued)}",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [],
                "stop_reason": "refusal",
                "stop_details": {
                    "type": "refusal",
                    "category": category,
                    "explanation": "declined",
                },
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }
        )
        return self

    def dies(self):
        """Queue a call the machine does not survive: the request goes out, and
        nothing ever comes back."""
        self._queue(_KILLED)
        return self

    def wait_for_paused_call(self, timeout: float) -> bool:
        """Block until a paused call is in flight."""
        return self._paused.wait(timeout)

    def counts_tokens(self, input_tokens: int):
        """Queue the answer to the next admission-gate token count."""
        self._token_counts.append(input_tokens)
        return self

    @property
    def uploads(self) -> list[str]:
        """Filenames sent to the Files API, in order."""
        return list(self._uploads)

    def _queue(self, body: object, pause: float = 0.0):
        self._queued.append((body, pause))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path

        # The Files API is multipart, not JSON, so it is answered before the
        # JSON-decoding the Messages endpoints rely on.
        if path.endswith("/v1/files"):
            self.file_requests.append(request)
            name = _multipart_filename(request.content) or f"upload-{len(self._uploads)}"
            self._uploads.append(name)
            file_id = f"file_{len(self._uploads) - 1:04d}"
            return httpx.Response(
                200,
                json={
                    "id": file_id,
                    "type": "file",
                    "filename": name,
                    "mime_type": "application/pdf",
                    "size_bytes": len(request.content),
                    "created_at": "2026-01-01T00:00:00Z",
                    "downloadable": False,
                },
            )

        if path.endswith("/count_tokens"):
            self.count_requests.append(json.loads(request.content))
            counted = self._token_counts.pop(0) if self._token_counts else 1000
            return httpx.Response(200, json={"input_tokens": counted})

        with self._lock:
            self.requests.append(json.loads(request.content))
            index = len(self.requests) - 1
            self._in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
            # The first topic call must finish alone: a cache entry only becomes
            # readable once the first response has begun, so anything running
            # alongside it misses and pays a write instead of a read.
            if index > 0 and self._in_flight > 1 and index == 1:
                self.overlapped_with_first = True
        if not self._queued:
            raise AssertionError(
                f"Claude was called {len(self.requests)} time(s) but only "
                f"{len(self.requests) - 1} response(s) were scripted"
            )
        body, pause = self._queued.pop(0)
        if pause:
            self._paused.set()
            time.sleep(pause)
        with self._lock:
            self._in_flight -= 1
        if body is _KILLED:
            raise MachineKilled("the machine was killed during this call")
        return httpx.Response(200, json=body)

    def client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(
            api_key="test-key-not-real",
            http_client=httpx.Client(transport=httpx.MockTransport(self._handle)),
        )


@pytest.fixture
def claude():
    return ClaudeScript()


@pytest.fixture
def identities():
    return Identities()


@pytest.fixture
def boot(tmp_path, claude, pg_dsn, identities):
    """Start an application over the volume.

    The database and data directory are the same on every call, so a second call
    is a restart of the machine: the new process boots against exactly what the
    old one left behind. Used as `with boot() as machine:` — leaving the block
    is the shutdown.
    """

    class Machine(TestClient):
        """A started machine, signed in as the test's person.

        The API is default-deny, so a client presenting no token can only
        observe 401s. Tests about the door itself clear the header to get back
        outside it; every other test wants to already be through.

        The credential is a header rather than a cookie, so it survives a
        restart without anything being stored — which is the point of moving
        sessions to the auth provider.
        """

        def __enter__(self):
            super().__enter__()
            self.sign_in_as(TESTER)
            return self

        def sign_in_as(self, account: str, **claims):
            self.headers.update(bearer(identities.token(account, **claims)))
            return self

        def sign_out(self):
            self.headers.pop("authorization", None)
            return self

    def _boot(**settings) -> TestClient:
        settings.setdefault("verifier", identities.verifier())
        return Machine(
            create_app(
                database_url=pg_dsn,
                data_dir=tmp_path / "data",
                anthropic_client=claude.client(),
                **settings,
            ),
            # Over https, because the application is served that way and a
            # request that claims otherwise is not the one production sees.
            base_url="https://testserver",
        )

    return _boot


@pytest.fixture
def client(boot):
    """A test client over a throwaway database and a scripted Claude.

    Tests drive the application through its HTTP boundary. Nothing below this
    seam is reached into directly.
    """
    with boot() as c:
        yield c


# --- Postgres ------------------------------------------------------------
#
# One container for the whole session, and a fresh schema per test. A
# transaction-rollback fixture would be faster and would break every test whose
# code commits -- which is every test that touches the worker, since a
# checkpoint that rolls back is not a checkpoint.


@pytest.fixture(scope="session")
def pg_container():
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
def pg_dsn(pg_container):
    import psycopg

    base = pg_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    schema = "t_" + _uuid.uuid4().hex[:16]
    admin = psycopg.connect(base, autocommit=True)
    admin.execute(f'CREATE SCHEMA "{schema}"')
    admin.close()
    try:
        yield f"{base}?options=-csearch_path%3D{schema}"
    finally:
        admin = psycopg.connect(base, autocommit=True)
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()
