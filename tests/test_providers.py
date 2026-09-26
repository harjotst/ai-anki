"""The model vendor, behind a narrow interface.

OpenAI is the only vendor. What stays behind `Provider` is exactly the part that
must not leak into the pipeline — how a document is attached, how caching is
expressed, how JSON is constrained, how a refusal is signalled, what it costs.
"""

import pytest

from app import providers
from app.providers import Capabilities, Prices, Reply, Usage
from app.providers.openai_provider import OpenAIProvider


def test_the_provider_satisfies_the_interface_with_a_dated_price():
    provider = OpenAIProvider(object())
    assert isinstance(provider, providers.Provider)
    assert provider.prices.verified_on, "a rate with no verification date is a guess"


def test_an_unpriced_model_is_refused_rather_than_billed_at_a_guess(the_model="made-up-4"):
    with pytest.raises(ValueError, match="unpriced"):
        OpenAIProvider(object(), model=the_model)


def test_the_model_can_be_chosen_by_environment_among_priced_ones(monkeypatch):
    monkeypatch.setenv("AI_ANKI_MODEL", "gpt-5.6-luna")
    assert providers.build(client=object()).model == "gpt-5.6-luna"

    monkeypatch.setenv("AI_ANKI_MODEL", "made-up-4")
    with pytest.raises(ValueError, match="unpriced"):
        providers.build(client=object())


def test_the_default_build_is_openai_and_passes_the_capability_gate():
    provider = providers.build(client=object())
    assert provider.name == "openai"
    assert provider.model == "gpt-5.6-luna"
    assert not providers.check_usable(provider), "Luna must pass the capability gate"


# --- the capability gate -------------------------------------------------


def gated(**overrides) -> Capabilities:
    base = dict(
        caching=True, cache_survives_minutes=60,
        native_documents=True, strict_schema=True, max_input_tokens=700_000,
    )
    return Capabilities(**{**base, **overrides})


class Stub:
    name, model = "stub", "stub-1"
    prices = Prices(1.0, 1.0, 1.0, 0.1, verified_on="2026-08-17")

    def __init__(self, capabilities):
        self.capabilities = capabilities


def test_a_provider_without_caching_is_refused_however_cheap_it_is():
    problems = providers.check_usable(Stub(gated(caching=False)))
    # Without caching the document is paid for once per topic call: on a 9-call
    # job that is roughly 3x the bill, which swamps any sticker-price saving.
    assert any("once per topic call" in p for p in problems)


def test_a_five_minute_cache_is_refused_because_a_human_reads_the_plan():
    problems = providers.check_usable(Stub(gated(cache_survives_minutes=5)))
    assert any("will not survive a user editing the plan" in p for p in problems)


def test_a_text_only_provider_is_refused_because_there_is_no_ocr_stage():
    problems = providers.check_usable(Stub(gated(native_documents=False)))
    assert any("no OCR stage" in p for p in problems)


def test_best_effort_json_is_not_accepted_as_schema_enforcement():
    problems = providers.check_usable(Stub(gated(strict_schema=False)))
    assert any("strict JSON" in p for p in problems)


def test_a_fully_capable_provider_has_nothing_against_it():
    assert providers.check_usable(Stub(gated())) == []


# --- pricing -------------------------------------------------------------


def test_usage_is_priced_at_the_models_own_rates():
    usage = Usage(input_tokens=1000, cache_write_tokens=200_000,
                  cache_read_tokens=1_600_000, output_tokens=14_000)

    cost = OpenAIProvider(object()).prices.cost(usage)

    # Worked independently at Luna's $0.20 in / $0.25 write / $0.02 read /
    # $1.20 out per MTok: 1k x 0.20 + 200k x 0.25 + 1.6M x 0.02 + 14k x 1.20
    # = $0.0002 + $0.05 + $0.032 + $0.0168 = $0.099.
    assert abs(cost - 0.099) < 0.0001


# --- request shape -------------------------------------------------------

SCHEMA = {"type": "object", "additionalProperties": False, "properties": {}}


def build(provider, cache="5m"):
    return provider.build_request(
        system="SYS", documents=[{"marker": 1}, {"marker": 2}],
        instruction="INSTRUCTION", schema=SCHEMA, max_tokens=16000, cache=cache,
    )


def test_documents_go_first_and_the_instruction_last():
    # The shared prefix is the whole cost model. If the varying instruction ever
    # lands before the documents, nothing errors — the bill just multiplies.
    openai_content = build(OpenAIProvider(object()))["input"][0]["content"]
    assert openai_content[0]["marker"] == 1
    assert openai_content[-1] == {"type": "input_text", "text": "INSTRUCTION"}


def test_asking_for_no_cache_marks_nothing_at_all():
    """A cache entry nothing reads still costs a write premium.

    Two requests carrying different JSON schemas get different cache lineages
    however identical their documents are. Caching a call whose schema nothing
    else shares is a pure loss, so it has to be possible to decline.
    """
    uncached = build(OpenAIProvider(object()), cache=None)
    assert "prompt_cache_options" not in uncached
    assert not any(
        "prompt_cache_breakpoint" in block for block in uncached["input"][0]["content"]
    )


def test_openai_marks_exactly_one_explicit_breakpoint_on_the_last_document():
    """Explicit rather than implicit: the automatic kind is best-effort, and
    the cost model rests on the hits.
    Verified against the versioned docs 2026-08-26: `prompt_cache_options`
    with mode explicit, "30m" the only TTL GPT-5.6+ accepts."""
    request = build(OpenAIProvider(object()))

    assert request["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    marked = [
        b for b in request["input"][0]["content"] if "prompt_cache_breakpoint" in b
    ]
    assert len(marked) == 1
    assert marked[0]["marker"] == 2


def test_openai_asks_for_strict_schema_enforcement():
    request = build(OpenAIProvider(object()))
    fmt = request["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert fmt["schema"] == SCHEMA


# --- the pipeline never builds a request by hand -----------------------


class FakeVendor:
    """A provider with a request shape deliberately unlike OpenAI's.

    The point is not to simulate any real vendor. It is to prove that nothing
    downstream of `Provider` knows or cares what the request looks like — if the
    pipeline still produces a deck through this, every pass really does go
    through the provider rather than hand-building an OpenAI request.
    """

    name, model = "fakevendor", "fake-1"
    prices = Prices(0.10, 0.40, 0.10, 0.01, verified_on="2026-08-17")
    capabilities = Capabilities(
        caching=True, cache_survives_minutes=45,
        native_documents=True, strict_schema=True, max_input_tokens=700_000,
    )

    def __init__(self):
        self.scripted: list[dict] = []
        self.sent: list[dict] = []
        self.uploads: list[str] = []

    def upload(self, path, filename):
        self.uploads.append(filename)
        return f"vendor-handle-{len(self.uploads)}"

    def document_block(self, *, path, filename, handle):
        # Nothing like OpenAI's shape, on purpose.
        return {"attachment": handle, "label": filename}

    def build_request(self, *, system, documents, instruction, schema, max_tokens, cache=None):
        return {
            "engine": self.model,
            "preamble": system,
            "payload": [*documents, {"say": instruction}],
            "shape": schema,
            "ceiling": max_tokens,
        }

    def count_input_tokens(self, request):
        return 1234

    def send(self, request):
        self.sent.append(request)
        # Every topic is taught before it is drilled. These tests are about the
        # provider abstraction rather than about lessons, so a lesson call is
        # answered from stock instead of having to be scripted -- the same
        # arrangement the scripted OpenAI transport uses, for the same reason.
        if "sections" in (request["shape"].get("properties") or {}):
            return Reply(
                data=STOCK_LESSON,
                usage=Usage(input_tokens=10, cache_read_tokens=5_000, output_tokens=100),
            )
        if not self.scripted:
            raise AssertionError("FakeVendor was called more times than it was scripted")
        return Reply(
            data=self.scripted.pop(0),
            usage=Usage(input_tokens=10, cache_read_tokens=5_000, output_tokens=100),
        )


from tests.conftest import STOCK_LESSON

PLAN = {
    "topics": [{
        "topic_id": "cells", "path": "Bio::Cells", "difficulty": "easy",
        "rationale": "Definitions.", "note_type": "basic",
        "proposed_card_count": 1, "claims": ["Mitochondria make ATP."],
    }]
}
CARDS = {"cards": [{
    "note_type": "basic", "front": "What makes ATP?", "back": "Mitochondria.",
    "source_page": 1, "existing_card_id": None,
}]}


@pytest.fixture
def vendor_client(tmp_path, pg_dsn, identities):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import TESTER, bearer

    vendor = FakeVendor()
    app = create_app(
        database_url=pg_dsn,
        data_dir=tmp_path / "data",
        provider=vendor,
        verifier=identities.verifier(),
    )
    with TestClient(app, base_url="https://testserver") as client:
        client.headers.update(bearer(identities.token(TESTER)))
        yield client, vendor


def test_a_deck_is_produced_end_to_end_through_the_interface_alone(vendor_client):
    client, vendor = vendor_client
    vendor.scripted = [PLAN, CARDS]

    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}, data={"deck_name": "Lecture"}
    ).json()["job_id"]
    assert client.post(f"/api/jobs/{job_id}/plan").status_code == 200
    assert client.post(f"/api/jobs/{job_id}/generate").status_code == 200

    cards = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]
    assert cards[0]["front"] == "What makes ATP?"

    # The .apkg is produced from the ledger, not from anything vendor-shaped.
    package = client.get(f"/api/jobs/{job_id}/deck.apkg")
    assert package.status_code == 200
    assert package.content[:2] == b"PK"


def test_the_pipeline_sends_the_vendors_own_request_shape(vendor_client):
    client, vendor = vendor_client
    vendor.scripted = [PLAN, CARDS]

    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}, data={"deck_name": "Lecture"}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")

    client.post(f"/api/jobs/{job_id}/generate")

    # EVERY pass, not just the first. An earlier version of this test only
    # checked the planning call and missed that the generation pass was still
    # building a vendor-shaped request by hand. Three now: plan, lesson,
    # cards -- and the lesson pass is exactly the kind of addition that could
    # have quietly reintroduced the bug.
    assert len(vendor.sent) == 3
    for sent in vendor.sent:
        assert set(sent) == {"engine", "preamble", "payload", "shape", "ceiling"}
        assert "input" not in sent and "text" not in sent
        # The prefix discipline holds regardless of shape: documents first,
        # varying instruction last.
        assert sent["payload"][0]["label"] == "lecture.txt"

    plan_call, lesson_call, cards_call = vendor.sent
    assert "deck plan" in plan_call["payload"][-1]["say"]
    assert "Teach one topic" in lesson_call["payload"][-1]["say"]
    assert "one topic only" in cards_call["payload"][-1]["say"]


def test_cost_is_billed_at_the_active_providers_rates(vendor_client):
    client, vendor = vendor_client
    vendor.scripted = [PLAN, CARDS]

    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}, data={"deck_name": "Lecture"}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")
    client.post(f"/api/jobs/{job_id}/generate")

    usage = client.get(f"/api/jobs/{job_id}/usage").json()
    # Three calls -- plan, lesson, cards -- each: 10 in @ $0.10
    #   + 5,000 cached @ $0.01 + 100 out @ $0.40
    #   = $0.000001 + $0.00005 + $0.00004 = $0.000091
    assert abs(usage["total_cost_usd"] - 3 * 0.000091) < 1e-6
    assert all(call["model"] == "fake-1" for call in usage["calls"])


def test_a_provider_that_fails_the_gate_is_rejected_at_startup(tmp_path, pg_dsn, identities):
    from app.main import create_app

    crippled = FakeVendor()
    crippled.capabilities = Capabilities(
        caching=True, cache_survives_minutes=5,
        native_documents=True, strict_schema=True, max_input_tokens=700_000,
    )

    # Refused when the app is built, not discovered halfway through a paid job.
    with pytest.raises(ValueError, match="cannot serve this workload"):
        create_app(
            database_url=pg_dsn,
            data_dir=tmp_path / "data",
            provider=crippled,
            verifier=identities.verifier(),
        )


# --- counting: OpenAI has no counting endpoint ---------------------------


class _Uploads:
    """Just enough client for `upload`: the Files API hands back an id."""

    def __init__(self):
        self.files = self

    def create(self, *, file, purpose):
        return type("Uploaded", (), {"id": "file-abc"})()


def test_text_is_counted_with_the_tokenizer_and_documents_are_estimated_by_page(tmp_path):
    """The admission gate has to work on what the app actually sends.

    Text — the system prompt, the instruction, inlined notes — is counted with
    the o200k tokenizer. An uploaded document has no local count, so it is
    estimated from its page count, deliberately high.
    """
    import pypdfium2

    from app.providers.openai_provider import TOKENS_PER_PAGE_ESTIMATE

    pdf = tmp_path / "metabolism.pdf"
    document = pypdfium2.PdfDocument.new()
    document.new_page(612, 792)
    document.new_page(612, 792)
    document.save(str(pdf))
    document.close()

    provider = OpenAIProvider(_Uploads())
    handle = provider.upload(pdf, "metabolism.pdf")
    block = provider.document_block(path=pdf, filename="metabolism.pdf", handle=handle)
    request = provider.build_request(
        system="SYS", documents=[block], instruction="GO", schema=SCHEMA, max_tokens=100,
    )

    assert request["input"][0]["content"][0] == {"type": "input_file", "file_id": "file-abc"}, (
        "the request that gets SENT references the upload"
    )
    counted = provider.count_input_tokens(request)
    assert 2 * TOKENS_PER_PAGE_ESTIMATE < counted < 2 * TOKENS_PER_PAGE_ESTIMATE + 50


def test_a_file_this_process_never_uploaded_is_estimated_rather_than_failing(tmp_path):
    """A resumed job runs in a process that did not do the uploading.

    It has a file id and no local copy, so exact counting is impossible. An
    estimate keeps the gate working; failing here would strand the job.
    """
    provider = OpenAIProvider(_Uploads())
    orphan = provider.document_block(
        path=tmp_path / "gone.pdf", filename="gone.pdf", handle="file-from-another-process"
    )
    request = provider.build_request(
        system="SYS", documents=[orphan], instruction="GO", schema=SCHEMA, max_tokens=100,
    )

    assert provider.count_input_tokens(request) > 10_000, (
        "the unknown document must contribute a pessimistic stand-in"
    )


def test_the_estimate_errs_high_because_that_is_the_cheaper_mistake(tmp_path):
    from app.providers.openai_provider import TOKENS_PER_PAGE_ESTIMATE, estimate_document_tokens

    # A PDF page is read as extracted text AND a rendered image, so a page is
    # thousands of tokens, not hundreds.
    assert TOKENS_PER_PAGE_ESTIMATE >= 3_000
    assert estimate_document_tokens(None) > 0
    assert estimate_document_tokens(tmp_path / "does-not-exist.pdf") > 0


# --- the OpenAI send path, against a scripted client ----------------------


class _FakeOpenAI:
    """Just enough client to hand `send` a canned Responses object."""

    def __init__(self, response):
        self.last_request = None
        outer = self

        class _Responses:
            def create(self, **request):
                outer.last_request = request
                return response

        self.responses = _Responses()


def _luna_response(*, text='{"ok": true}', status="completed", reason=None,
                   input_tokens=0, cached=0, written=0, output_tokens=0):
    from types import SimpleNamespace as NS

    return NS(
        status=status,
        incomplete_details=NS(reason=reason),
        output=[],
        output_text=text,
        usage=NS(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_tokens_details=NS(cached_tokens=cached, cache_write_tokens=written),
        ),
    )


def test_openai_usage_is_derived_the_way_the_bill_is_split():
    """OpenAI reports cached and written tokens INSIDE input_tokens; billing
    them again at the plain rate would double-count exactly the tokens the
    cache exists to discount."""
    client = _FakeOpenAI(_luna_response(input_tokens=1000, cached=600, written=300, output_tokens=50))
    reply = OpenAIProvider(client).send({"model": "gpt-5.6-luna"})

    assert reply.usage.input_tokens == 100
    assert reply.usage.cache_read_tokens == 600
    assert reply.usage.cache_write_tokens == 300
    assert reply.usage.output_tokens == 50


def test_openai_truncation_is_unusable_rather_than_parsed():
    client = _FakeOpenAI(_luna_response(status="incomplete", reason="max_output_tokens"))
    with pytest.raises(providers.Unusable, match="max_output_tokens"):
        OpenAIProvider(client).send({"model": "gpt-5.6-luna"})


def test_openai_refusals_are_unusable_with_the_reason_kept():
    from types import SimpleNamespace as NS

    response = _luna_response()
    response.output = [NS(content=[NS(type="refusal", refusal="declined")])]
    client = _FakeOpenAI(response)
    with pytest.raises(providers.Unusable, match="declined"):
        OpenAIProvider(client).send({"model": "gpt-5.6-luna"})


def test_a_file_handle_left_by_an_earlier_vendor_is_never_sent(pg_dsn, tmp_path):
    """File ids mean nothing across vendors. A job whose sources were uploaded
    to the vendor this app used before must re-upload to OpenAI, not hand it
    an id it never issued."""
    from app import db, jobs

    class Vendor:
        def __init__(self, name):
            self.name = name
            self.uploads = []

        def upload(self, path, filename):
            self.uploads.append(filename)
            return f"{self.name}-handle"

        def document_block(self, *, path, filename, handle):
            return {"handle": handle}

    db.initialise(pg_dsn)
    conn = db.connect(pg_dsn)
    try:
        job_id = jobs.create_job(
            conn, tmp_path, "notes.pdf", b"%PDF-1.4 stub", account_id=None, deck_name="Notes"
        )

        first = Vendor("previous-vendor")
        jobs.documents_for(conn, job_id, first)
        assert first.uploads == ["notes.pdf"]

        second = Vendor("openai")
        blocks = jobs.documents_for(conn, job_id, second)
        assert second.uploads == ["notes.pdf"], "another vendor's handle was reused"
        assert blocks == [{"handle": "openai-handle"}]

        # Its own handle, though, IS remembered: at most one upload per vendor.
        third = Vendor("openai")
        jobs.documents_for(conn, job_id, third)
        assert third.uploads == []
    finally:
        conn.close()


def test_a_rate_limit_is_a_request_to_wait_not_a_failure():
    """A 429 carries its own remedy — "try again in 19s" — and recording it
    as a dead topic wastes exactly the call a pause would have saved.
    Observed live 2026-08-26: a five-topic fan-out of 64k-token calls
    against a 200k-TPM organization limit failed four topics this way."""
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(429, request=request, headers={"retry-after": "19"})

    class Limited:
        class responses:
            @staticmethod
            def create(**_request):
                raise openai.RateLimitError(
                    "Rate limit reached on tokens per min (TPM). Please try again in 19.14s.",
                    response=response,
                    body=None,
                )

    with pytest.raises(providers.RateLimited) as caught:
        OpenAIProvider(Limited()).send({"model": "gpt-5.6-luna"})
    assert caught.value.retry_after == 19.0
