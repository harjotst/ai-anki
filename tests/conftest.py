import json
import threading
import time
import uuid as _uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app import identity
from app.main import create_app
from app.providers.openai_provider import OpenAIProvider

# --- who the tests are signed in as --------------------------------------
#
# Real RSA keys, real JWTs, real verification. Only the JWKS *fetch* is
# replaced, which is the same seam `ModelScript` uses for the OpenAI
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
    faithful: the OpenAI SDK turns any `Exception` from the transport into an
    `APIConnectionError` and retries it, which is the opposite of a machine
    dying. Nothing recovers from this one — the process that hits it is
    finished, so whatever a job knows afterwards it committed beforehand.
    """


_KILLED = object()

# What an unremarkable lesson looks like. Shape matters here, not prose: it has
# to satisfy the schema so that anything reading a lesson back gets a real one.
STOCK_LESSON = {
    "in_one_line": "The topic, in one sentence.",
    "why_it_matters": "Why somebody studying this course needs it.",
    "sections": [
        {"heading": "The first idea", "body": "What it is and why.", "builds_on": None}
    ],
    "worked_example": None,
    "misconceptions": [
        {"belief": "A common wrong idea.", "why_it_is_wrong": "Because of this."}
    ],
    "check_yourself": ["Can you explain it without the notes?"],
}

MODEL = "gpt-5.6-luna"


def _wire_usage(usage: dict | None) -> dict:
    """Usage as the Responses API reports it.

    Tests speak in the application's own terms — uncached input, cache writes,
    cache reads, output. OpenAI folds cached and written tokens INTO the input
    count, so the wire total is the sum, and the provider has to take it apart
    again. Faking it the vendor's way is what tests that arithmetic.
    """
    usage = {
        "input_tokens": 100,
        "cache_write_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 50,
        **(usage or {}),
    }
    total_input = usage["input_tokens"] + usage["cache_write_tokens"] + usage["cache_read_tokens"]
    return {
        "input_tokens": total_input,
        "input_tokens_details": {
            "cached_tokens": usage["cache_read_tokens"],
            "cache_write_tokens": usage["cache_write_tokens"],
        },
        "output_tokens": usage["output_tokens"],
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": total_input + usage["output_tokens"],
    }


def _response(content: list[dict], *, usage: dict | None = None, status: str = "completed",
              incomplete_reason: str | None = None) -> dict:
    return {
        "id": "resp_scripted",
        "object": "response",
        "created_at": 0,
        "model": MODEL,
        "status": status,
        "incomplete_details": {"reason": incomplete_reason} if incomplete_reason else None,
        "output": [
            {
                "type": "message",
                "id": "msg_scripted",
                "status": status,
                "role": "assistant",
                "content": content,
            }
        ],
        "usage": _wire_usage(usage),
    }


def _text_response(text: str, usage: dict | None = None, *, truncated: bool = False) -> dict:
    return _response(
        [{"type": "output_text", "text": text, "annotations": []}],
        usage=usage,
        status="incomplete" if truncated else "completed",
        incomplete_reason="max_output_tokens" if truncated else None,
    )


class ModelScript:
    """A scripted OpenAI API, faked at the network transport only.

    The real SDK stays in the loop — only the HTTP boundary is replaced — so SDK
    misuse still fails tests and the application needs no test-only seam of its
    own. Tests queue response bodies; requests are recorded for assertions.

    Token counting is the one exception. OpenAI has no counting endpoint, so
    the provider counts locally; `counts_tokens` scripts that answer through
    `ScriptedCountProvider`, which is how a test says "this job is huge"
    without shipping a huge document.
    """

    def __init__(self):
        self._queued: list[tuple[object, float]] = []
        self.requests: list[dict] = []
        # The admission gate and the Files API are separate from generation;
        # keeping their traffic apart is what lets a test say "nothing was
        # generated".
        self.count_requests: list[dict] = []
        self.file_requests: list[httpx.Request] = []
        self._token_counts: list[int] = []
        self._uploads: list[str] = []
        self._paused = threading.Event()
        # How many calls are in flight at once, and the high-water mark. This
        # is what lets a test assert the SHAPE of the fan-out rather than its
        # wall-clock, which would be flaky.
        self._by_kind: dict = {}
        self._kind_usage: dict | None = None
        self._kind_pause: dict = {}
        self._in_flight = 0
        self.peak_in_flight = 0
        self.overlapped_with_first = False
        self._lock = threading.Lock()

    def replies(
        self,
        text: str,
        *,
        truncated: bool = False,
        usage: dict | None = None,
        pause: float = 0.0,
    ):
        """Queue a normal reply whose output text is `text`.

        `truncated` ends it the way running out of output tokens does.
        `pause` holds the call open, the way a real topic call does for minutes
        at a time — long enough for something else to happen to the machine
        while it is waiting.
        """
        self._queue(_text_response(text, usage, truncated=truncated), pause)
        return self

    def replies_json(self, payload: dict, **kwargs):
        return self.replies(json.dumps(payload), **kwargs)

    def answers(self, *, usage: dict | None = None, pause: dict | None = None, **by_kind):
        """Answer according to what was asked, rather than in call order.

        The queue is FIFO, which is exactly right while calls are sequential and
        wrong the moment they are not: topics fan out concurrently, each making
        a lesson call and a cards call, so the arrival order of six calls across
        three topics is not something a test should have to predict.

        A responder keys off the response schema instead — `lesson=`, `cards=`,
        `topics=` — so the same script works however the calls interleave.
        Accepts a dict, or a callable taking the request for tests that care
        which topic they are answering.

        Pass `usage=` to give every answer the same reported token usage,
        which is how a test says "these calls read the cache" without caring
        which call was which. Pass `pause={"cards": 1.0}` to hold calls of one
        kind open, the way a real one runs for a while, so a test can look at
        what the job has already committed while the rest is still in flight.
        """
        self._by_kind = dict(by_kind)
        self._kind_usage = usage
        self._kind_pause = pause or {}
        return self

    def calls_for(self, kind: str) -> list[dict]:
        """Every request that asked for one kind of thing.

        Each topic makes two calls, and they interleave, so asking by kind says
        what was meant where call order cannot.
        """
        return [r for r in self.requests if self._kind_of(r) == kind]

    @staticmethod
    def _kind_of(request: dict) -> str | None:
        """What a request is asking for, read off its response schema."""
        schema = ((request.get("text") or {}).get("format") or {}).get("schema", {})
        properties = set(schema.get("properties") or {})
        if "topics" in properties:
            return "topics"
        if "cards" in properties:
            return "cards"
        if "sections" in properties:
            return "lesson"
        return None

    def refuses(self, reason: str = "I can't help with that."):
        """Queue a safety refusal — HTTP 200, a refusal part, no text."""
        self._queue(
            _response(
                [{"type": "refusal", "refusal": reason}],
                usage={"input_tokens": 0, "output_tokens": 0},
            )
        )
        return self

    def dies(self):
        """Queue a call the machine does not survive: the request goes out, and
        nothing ever comes back."""
        self._queue(_KILLED)
        return self

    def answers_error(self, status: int, message: str):
        """Queue an HTTP error from the API itself — a 400, an overload.

        Distinct from `dies`: the machine survives this, and what matters is
        what it does with a job whose call just refused to run.
        """
        self._queue({"__error_status__": status, "__error_message__": message})
        return self

    def wait_for_paused_call(self, timeout: float) -> bool:
        """Block until a paused call is in flight."""
        return self._paused.wait(timeout)

    def counts_tokens(self, input_tokens: int):
        """Queue the answer to the next admission-gate token count."""
        self._token_counts.append(input_tokens)
        return self

    def count(self, request: dict) -> int:
        self.count_requests.append(request)
        return self._token_counts.pop(0) if self._token_counts else 1000

    @property
    def uploads(self) -> list[str]:
        """Filenames sent to the Files API, in order."""
        return list(self._uploads)

    def _queue(self, body: object, pause: float = 0.0):
        self._queued.append((body, pause))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path

        # The Files API is multipart, not JSON, so it is answered before the
        # JSON-decoding the Responses endpoint relies on.
        if path.endswith("/v1/files"):
            self.file_requests.append(request)
            name = _multipart_filename(request.content) or f"upload-{len(self._uploads)}"
            self._uploads.append(name)
            file_id = f"file-{len(self._uploads) - 1:04d}"
            return httpx.Response(
                200,
                json={
                    "id": file_id,
                    "object": "file",
                    "bytes": len(request.content),
                    "created_at": 0,
                    "filename": name,
                    "purpose": "user_data",
                    "status": "processed",
                },
            )

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
        request = self.requests[index]

        kind = self._kind_of(request)
        if kind == "lesson" and "lesson" not in self._by_kind:
            # Every topic is taught before it is drilled, so a lesson call now
            # happens in almost every test. Answering it from stock keeps the
            # tests that are about something else -- slot matching, budgets,
            # shutdown -- from having to know lessons exist at all. A test that
            # cares what was taught says so with `answers(lesson=...)`.
            with self._lock:
                self._in_flight -= 1
            return httpx.Response(200, json=_text_response(json.dumps(STOCK_LESSON)))
        if kind in self._by_kind:
            answer = self._by_kind[kind]
            body = _text_response(
                json.dumps(answer(request) if callable(answer) else answer), self._kind_usage
            )
            pause = self._kind_pause.get(kind, 0.0)
        elif not self._queued:
            raise AssertionError(
                f"The model was called {len(self.requests)} time(s) but only "
                f"{len(self.requests) - 1} response(s) were scripted"
            )
        else:
            body, pause = self._queued.pop(0)
        if pause:
            self._paused.set()
            time.sleep(pause)
        with self._lock:
            self._in_flight -= 1
        if body is _KILLED:
            raise MachineKilled("the machine was killed during this call")
        if isinstance(body, dict) and "__error_status__" in body:
            return httpx.Response(
                body["__error_status__"],
                json={
                    "error": {
                        "message": body["__error_message__"],
                        "type": "invalid_request_error",
                        "param": None,
                        "code": None,
                    }
                },
            )
        return httpx.Response(200, json=body)

    def client(self) -> openai.OpenAI:
        return openai.OpenAI(
            api_key="test-key-not-real",
            http_client=httpx.Client(transport=httpx.MockTransport(self._handle)),
        )


class ScriptedCountProvider(OpenAIProvider):
    """The real OpenAI provider, with its local token count scripted.

    Everything else — request shapes, uploads, usage, refusals — runs as it
    does in production.
    """

    def __init__(self, script: ModelScript, **kwargs):
        super().__init__(script.client(), **kwargs)
        self._script = script

    def count_input_tokens(self, request: dict) -> int:
        return self._script.count(request)


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    """An operator's shell may set AI_ANKI_MODEL; the scripted machine must
    not quietly run as some other model than the one the tests price."""
    monkeypatch.delenv("AI_ANKI_MODEL", raising=False)


@pytest.fixture
def llm():
    return ModelScript()


@pytest.fixture
def identities():
    return Identities()


@pytest.fixture
def boot(tmp_path, llm, pg_dsn, identities):
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
            # An email by default, because a real token carries one and a
            # nameless account is a screen with a blank where a person should be.
            claims.setdefault("email", f"{account[-4:]}@example.test")
            self.headers.update(bearer(identities.token(account, **claims)))
            return self

        def sign_out(self):
            self.headers.pop("authorization", None)
            return self

    def _boot(**settings) -> TestClient:
        settings.setdefault("verifier", identities.verifier())
        settings.setdefault("provider", ScriptedCountProvider(llm))
        return Machine(
            create_app(
                database_url=pg_dsn,
                data_dir=tmp_path / "data",
                **settings,
            ),
            # Over https, because the application is served that way and a
            # request that claims otherwise is not the one production sees.
            base_url="https://testserver",
        )

    return _boot


@pytest.fixture
def client(boot):
    """A test client over a throwaway database and a scripted model.

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

    # 17, matching what the project actually runs. Testing against a different
    # major than production is how a behaviour difference reaches a user before
    # it reaches a test.
    with PostgresContainer("postgres:17-alpine") as container:
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
