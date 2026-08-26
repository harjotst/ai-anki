"""Swapping model vendors.

The interface is narrow on purpose. What differs between vendors is exactly the
part that does not generalise — how a document is attached, how caching is
expressed, how JSON is constrained, how a refusal is signalled — so all of it
lives behind `Provider` and none of it leaks into the pipeline.
"""

import pytest

from app import providers
from app.providers import Capabilities, Prices, Reply, Usage
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.gemini_provider import GeminiProvider


def test_both_providers_satisfy_the_same_interface():
    for provider in (AnthropicProvider(object()), GeminiProvider(object())):
        assert isinstance(provider, providers.Provider)
        assert provider.prices.verified_on, "a rate with no verification date is a guess"


def test_an_unpriced_model_is_refused_rather_than_billed_at_a_guess(the_model="made-up-4"):
    with pytest.raises(ValueError, match="unpriced"):
        AnthropicProvider(object(), model=the_model)
    with pytest.raises(ValueError, match="unpriced"):
        GeminiProvider(object(), model=the_model)


def test_an_unknown_provider_is_refused_rather_than_defaulted():
    # Silently falling back to a default the operator did not ask for is how you
    # get a surprise bill from the vendor you thought you had switched away from.
    with pytest.raises(ValueError, match="unknown provider"):
        providers.build("acme-ai", client=object())


def test_the_provider_is_chosen_by_environment_so_swapping_is_a_redeploy(monkeypatch):
    monkeypatch.setenv("AI_ANKI_PROVIDER", "gemini")
    monkeypatch.setenv("AI_ANKI_MODEL", "gemini-3.1-flash-lite")

    provider = providers.build(client=object())

    assert provider.name == "gemini"
    assert provider.model == "gemini-3.1-flash-lite"


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


def test_each_provider_prices_the_same_usage_with_its_own_rates():
    usage = Usage(input_tokens=1000, cache_write_tokens=200_000,
                  cache_read_tokens=1_600_000, output_tokens=14_000)

    opus = AnthropicProvider(object(), model="claude-opus-5").prices.cost(usage)
    sonnet = AnthropicProvider(object(), model="claude-sonnet-5").prices.cost(usage)
    flash = GeminiProvider(object()).prices.cost(usage, cache_hours=1 / 6)

    # Worked independently: Opus 5 is 200k x $10 write + 1.6M x $0.50 read +
    # 14k x $25 out + 1k x $5 in = $2.00 + $0.80 + $0.35 + $0.005 = $3.155.
    assert abs(opus - 3.155) < 0.001
    # Sonnet 5 on the identical request shape, for a one-line change.
    assert sonnet < opus / 2
    assert flash < opus / 5


def test_only_google_rents_cached_content_by_the_hour():
    usage = Usage(cache_write_tokens=200_000)

    anthropic_cost = AnthropicProvider(object()).prices.cost(usage, cache_hours=10)
    gemini_cost = GeminiProvider(object()).prices.cost(usage, cache_hours=10)

    assert AnthropicProvider(object()).prices.storage_per_mtok_hour == 0.0
    assert anthropic_cost == AnthropicProvider(object()).prices.cost(usage, cache_hours=0)
    assert gemini_cost > GeminiProvider(object()).prices.cost(usage, cache_hours=0)


def test_the_gemini_cache_write_rate_is_flagged_as_an_assumption():
    from app.providers import gemini_provider

    # Google publishes no cache-write multiplier anywhere. The headline saving
    # rests on assuming creation bills at plain input rate, and that must not
    # quietly become folklore.
    assert gemini_provider.CACHE_WRITE_IS_ASSUMED is True
    assert gemini_provider.MODELS["gemini-3.7-flash"].cache_write == (
        gemini_provider.MODELS["gemini-3.7-flash"].input
    )


# --- request shape -------------------------------------------------------

SCHEMA = {"type": "object", "additionalProperties": False, "properties": {}}


def build(provider, cache="5m"):
    return provider.build_request(
        system="SYS", documents=[{"marker": 1}, {"marker": 2}],
        instruction="INSTRUCTION", schema=SCHEMA, max_tokens=16000, cache=cache,
    )


def test_every_provider_puts_documents_first_and_the_instruction_last():
    # The shared prefix is the whole cost model. If the varying instruction ever
    # lands before the documents, nothing errors — the bill just multiplies.
    anthropic_content = build(AnthropicProvider(object()))["messages"][0]["content"]
    assert anthropic_content[0]["marker"] == 1
    assert anthropic_content[-1]["text"] == "INSTRUCTION"

    gemini_parts = build(GeminiProvider(object()))["contents"][0]["parts"]
    assert gemini_parts[0]["marker"] == 1
    assert gemini_parts[-1]["text"] == "INSTRUCTION"


def test_anthropic_marks_exactly_one_breakpoint_on_the_last_document():
    content = build(AnthropicProvider(object()))["messages"][0]["content"]

    marked = [b for b in content if "cache_control" in b]
    assert len(marked) == 1
    assert marked[0]["marker"] == 2
    assert marked[0]["cache_control"]["ttl"] == "5m"


def test_asking_for_no_cache_marks_nothing_at_all():
    """A cache entry nothing reads still costs a write premium.

    Measured against the live API on 2026-08-17: two requests carrying
    different JSON schemas get different cache lineages however identical
    their documents are. Caching a call whose schema nothing else shares is a
    pure loss, so it has to be possible to decline.
    """
    content = build(AnthropicProvider(object()), cache=None)["messages"][0]["content"]
    assert not any("cache_control" in block for block in content)

    config = build(GeminiProvider(object()), cache=None)["config"]
    assert "cached_content_ttl_seconds" not in config


def test_gemini_asks_for_an_explicit_cache_rather_than_a_best_effort_one():
    config = build(GeminiProvider(object()))["config"]

    # Implicit caching is free to store but its hits are best-effort, which is
    # not good enough when the entire cost model rests on them.
    assert config["cached_content_ttl_seconds"] == 5 * 60
    assert config["response_json_schema"] == SCHEMA


# --- the whole pipeline, on a vendor that is not Anthropic ---------------


class FakeVendor:
    """A provider with a request shape deliberately unlike Anthropic's.

    The point is not to simulate any real vendor. It is to prove that nothing
    downstream of `Provider` knows or cares what the request looks like — if the
    pipeline still produces a deck through this, the abstraction is real rather
    than Anthropic wearing an interface.
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
        # Nothing like Anthropic's shape, on purpose.
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
        # arrangement the Anthropic fake uses, for the same reason.
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


def test_a_deck_is_produced_end_to_end_on_a_non_anthropic_provider(vendor_client):
    client, vendor = vendor_client
    vendor.scripted = [PLAN, CARDS]

    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}
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
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")

    client.post(f"/api/jobs/{job_id}/generate")

    # EVERY pass, not just the first. An earlier version of this test only
    # checked the planning call and missed that the generation pass was still
    # building an Anthropic-shaped request by hand. Three now: plan, lesson,
    # cards -- and the lesson pass is exactly the kind of addition that could
    # have quietly reintroduced the bug.
    assert len(vendor.sent) == 3
    for sent in vendor.sent:
        assert set(sent) == {"engine", "preamble", "payload", "shape", "ceiling"}
        assert "output_config" not in sent and "messages" not in sent
        # The prefix discipline holds regardless of shape: documents first,
        # varying instruction last.
        assert sent["payload"][0]["label"] == "lecture.txt"

    plan_call, lesson_call, cards_call = vendor.sent
    assert "deck plan" in plan_call["payload"][-1]["say"]
    assert "Teach one topic" in lesson_call["payload"][-1]["say"]
    assert "one topic only" in cards_call["payload"][-1]["say"]


def test_cost_is_billed_at_the_active_providers_rates_not_anthropics(vendor_client):
    client, vendor = vendor_client
    vendor.scripted = [PLAN, CARDS]

    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}
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


# --- counting a document that was uploaded rather than inlined -----------


class CountingClient:
    """Stands in for the real endpoint's refusal to accept file sources.

    Verbatim from the live API on 2026-08-21:
        400 — "File sources are not supported in the token counting endpoint."
    """

    def __init__(self):
        self.counted: list[dict] = []
        self.beta = self

    @property
    def files(self):
        return self

    @property
    def messages(self):
        return self

    def upload(self, file):
        return type("Uploaded", (), {"id": "file_abc"})()

    def count_tokens(self, *, model, system, messages, betas):
        for message in messages:
            for block in message.get("content", []):
                source = block.get("source") if isinstance(block, dict) else None
                if source and source.get("type") == "file":
                    raise AssertionError(
                        "File sources are not supported in the token counting endpoint"
                    )
        self.counted.append({"messages": messages})
        return type("Counted", (), {"input_tokens": 4321})()


def test_an_uploaded_document_is_counted_by_inlining_the_same_bytes(tmp_path):
    """The admission gate has to work on the format the app actually uploads.

    This was a live 500 on the first real PDF: the gate counted the assembled
    request, the request referenced an uploaded file, and the endpoint refuses
    file sources.
    """
    pdf = tmp_path / "metabolism.pdf"
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 2048)

    client = CountingClient()
    provider = AnthropicProvider(client)
    handle = provider.upload(pdf, "metabolism.pdf")
    block = provider.document_block(path=pdf, filename="metabolism.pdf", handle=handle)
    request = provider.build_request(
        system="SYS", documents=[block], instruction="GO", schema=SCHEMA, max_tokens=100,
    )

    assert request["messages"][0]["content"][0]["source"]["type"] == "file", (
        "the request that gets SENT still references the upload"
    )

    counted = provider.count_input_tokens(request)

    assert counted == 4321
    # ...but what was counted carried the bytes inline.
    sent_for_counting = client.counted[0]["messages"][0]["content"][0]
    assert sent_for_counting["source"]["type"] == "base64"
    assert sent_for_counting["source"]["media_type"] == "application/pdf"


def test_a_file_this_process_never_uploaded_is_estimated_rather_than_failing(tmp_path):
    """A resumed job runs in a process that did not do the uploading.

    It has a file_id and no local copy, so exact counting is impossible. An
    estimate keeps the gate working; failing here would strand the job.
    """
    client = CountingClient()
    provider = AnthropicProvider(client)
    orphan = provider.document_block(
        path=tmp_path / "gone.pdf", filename="gone.pdf", handle="file_from_another_process"
    )
    request = provider.build_request(
        system="SYS", documents=[orphan], instruction="GO", schema=SCHEMA, max_tokens=100,
    )

    counted = provider.count_input_tokens(request)

    # The measured remainder plus a pessimistic stand-in for the document.
    assert counted > 4321, "the unknown document must contribute something"


def test_the_estimate_errs_high_because_that_is_the_cheaper_mistake(tmp_path):
    from app.providers.anthropic_provider import TOKENS_PER_PAGE_ESTIMATE, estimate_document_tokens

    # Claude bills every PDF page as extracted text AND a rendered image, so a
    # page is thousands of tokens, not hundreds.
    assert TOKENS_PER_PAGE_ESTIMATE >= 3_000
    assert estimate_document_tokens(None) > 0
    assert estimate_document_tokens(tmp_path / "does-not-exist.pdf") > 0


def test_fallbacks_goes_only_to_the_model_that_accepts_it(claude):
    """Sonnet 5 refuses the whole request over a parameter Opus 5 accepts.

    Not hypothetical: the live API answered 400 to a real planning run on
    2026-08-26 (req_011CeQfD9jcBcLEpdiDRjox7) because `fallbacks` was sent
    unconditionally. The transport in these tests now enforces the same
    contract, so sending it to the wrong model fails loudly here first.
    """
    schema = {"type": "object", "additionalProperties": False, "properties": {}}

    opus = AnthropicProvider(claude.client(), model="claude-opus-5")
    claude.replies_json({})
    opus.send(opus.build_request(
        system="s", documents=[], instruction="i", schema=schema, max_tokens=64
    ))
    assert claude.requests[-1]["fallbacks"] == "default"

    sonnet = AnthropicProvider(claude.client(), model="claude-sonnet-5")
    claude.replies_json({})
    sonnet.send(sonnet.build_request(
        system="s", documents=[], instruction="i", schema=schema, max_tokens=64
    ))
    assert "fallbacks" not in claude.requests[-1]
