"""The cost model, made real and then checked against what the API reported.

Caching here is not an optimisation, it is the design. Pass 1 writes the whole
document into the cache; every topic call then reads it at a tenth of the price.
If the shared prefix drifts by one byte, every topic call silently pays full
freight instead — nothing errors, the bill just multiplies.
"""

from app import ingestion

PLAN = {
    "topics": [
        {
            "topic_id": f"t{n}",
            "path": f"Bio::Topic {n}",
            "difficulty": "medium",
            "rationale": "Mixed.",
            "note_type": "basic",
            "proposed_card_count": 2,
        }
        for n in (1, 2)
    ]
}

CARDS = {"cards": [{"note_type": "basic", "front": "Q?", "back": "A.", "source_page": 1}]}

# What the API reports back: pass 1 writes the cache, each topic call reads it.
WROTE_CACHE = {"input_tokens": 500, "cache_write_tokens": 200_000, "output_tokens": 2_000}
READ_CACHE = {"input_tokens": 400, "cache_read_tokens": 200_000, "output_tokens": 1_000}


def upload(client):
    return client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}, data={"deck_name": "Lecture"}
    ).json()["job_id"]


def run_job(client, llm):
    llm.counts_tokens(200_000).replies_json(PLAN, usage=WROTE_CACHE)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    llm.answers(cards=CARDS, usage=READ_CACHE)
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id


def test_every_topic_call_sends_a_byte_identical_cacheable_prefix(client, llm):
    """The topic calls share with each other. That is where the saving is.

    They do NOT share with the planning pass, and no amount of prefix
    discipline will make them: a request carrying a different JSON schema gets
    its own cache lineage.
    """
    run_job(client, llm)
    # By kind, not by position. Each topic now makes two calls -- a lesson and
    # its cards -- and they interleave across a concurrent fan-out, so an index
    # says nothing. Cards share a lineage with cards; lessons with lessons.
    plan_request = llm.calls_for("topics")[0]
    first, *rest = llm.calls_for("cards")
    for request in rest:
        assert request["instructions"] == first["instructions"], "a per-call system prompt kills the cache"
        assert request["input"][0]["content"][0] == first["input"][0]["content"][0]
        assert request["text"]["format"] == first["text"]["format"], (
            "a differing schema puts this call in its own cache lineage"
        )
        # Reasoning settings and tools are pinned across passes rather than
        # trusting an invalidation rule we have not confirmed live.
        assert request.get("reasoning") == plan_request.get("reasoning")
        assert request.get("tools") == plan_request.get("tools")


def test_the_planning_pass_does_not_pay_for_a_cache_nothing_reads(client, llm):
    """Measured, not assumed. This was a real bug found on the first live call.

    The planning pass is the only call in a job sending DECK_PLAN_SCHEMA, so
    nothing ever reads what it writes — and a cache write costs more than
    plain input. It was pure waste.
    """
    run_job(client, llm)

    plan_request = llm.requests[0]
    assert "prompt_cache_options" not in plan_request
    assert not any(
        "prompt_cache_breakpoint" in block for block in plan_request["input"][0]["content"]
    )


def test_the_topic_calls_mark_one_explicit_breakpoint_after_the_documents(client, llm):
    run_job(client, llm)

    request = llm.calls_for("cards")[0]
    content = request["input"][0]["content"]
    documents, instruction = content[:-1], content[-1]

    assert "prompt_cache_breakpoint" not in instruction, (
        "the varying instruction goes after the breakpoint"
    )
    assert documents[-1]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    # Explicit, not best-effort: the cost model rests on the hits.
    assert request["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    # Exactly one breakpoint: the cache is a prefix match, so marking earlier
    # blocks caches strictly less.
    assert sum("prompt_cache_breakpoint" in block for block in content) == 1


def test_generation_reads_the_cache_the_planning_pass_wrote(client, llm):
    job_id = run_job(client, llm)

    calls = client.get(f"/api/jobs/{job_id}/usage").json()["calls"]

    plan_call = next(c for c in calls if c["pass_name"] == "plan")
    topic_calls = [c for c in calls if c["pass_name"] == "cards"]

    assert plan_call["cache_creation_input_tokens"] == 200_000
    assert plan_call["cache_read_input_tokens"] == 0

    assert len(topic_calls) == 2
    for call in topic_calls:
        assert call["cache_read_input_tokens"] > 0, "a topic call that writes is a broken prefix"
        assert call["cache_creation_input_tokens"] == 0


def test_the_job_reports_what_it_actually_cost_not_what_it_was_estimated_to(client, llm):
    job_id = run_job(client, llm)

    usage = client.get(f"/api/jobs/{job_id}/usage").json()

    # Worked by hand from the scripted usage, independently of the code, at
    # GPT-5.6 Luna's rates ($0.20 in / $0.25 cache write / $0.02 cache read /
    # $1.20 out, per MTok):
    #   plan   500 uncached                 = $0.0001
    #          200,000 cache write          = $0.0500
    #          2,000 output                 = $0.0024
    #   cards  2 x (400 uncached            = $0.00008
    #               200,000 cache read      = $0.004
    #               1,000 output            = $0.0012)
    #   lesson 2 x (100 uncached            = $0.00002
    #               50 output               = $0.00006)
    #
    # The lesson line is small here only because the fake's stock usage is
    # small. On a real job it is the same order as the cards, which is the
    # number the estimate has to carry.
    expected = 0.0001 + 0.05 + 0.0024 + 2 * (0.00008 + 0.004 + 0.0012) + 2 * (0.00002 + 0.00006)
    assert abs(usage["total_cost_usd"] - expected) < 0.00001
    assert usage["total_cost_usd"] > 0


def test_a_cached_run_costs_a_fraction_of_what_it_would_uncached(client, llm):
    """The claim the two-pass design is built on, stated as a number."""
    job_id = run_job(client, llm)
    actual = client.get(f"/api/jobs/{job_id}/usage").json()["total_cost_usd"]

    # Had each topic call paid full price for the same 200k document instead of
    # reading it, the input alone would have been 2 x 200,000 at the input rate.
    # Priced off the provider's own sheet, never a separate table.
    from app.providers.openai_provider import DEFAULT_MODEL, MODELS

    prices = MODELS[DEFAULT_MODEL]
    uncached_topic_input = 2 * 200_000 * prices.input / 1_000_000
    cached_topic_input = 2 * 200_000 * prices.cache_read / 1_000_000
    plan_write = 200_000 * prices.cache_write / 1_000_000

    assert cached_topic_input < uncached_topic_input / 5
    # The whole cached run — plan included — costs less than the topic calls'
    # input alone would have uncached, plus the one write they all read.
    assert actual < uncached_topic_input + plan_write


def test_no_topic_call_is_made_until_the_planning_pass_has_returned(client, llm):
    """A cache entry is only readable once the first response has begun.

    Fanning out before pass 1 returns would have every topic call miss and pay a
    cache-write charge — worse than not caching at all.
    """
    llm.counts_tokens(200_000).replies_json(PLAN, usage=WROTE_CACHE)
    job_id = upload(client)

    client.post(f"/api/jobs/{job_id}/plan")
    assert len(llm.requests) == 1, "planning must not trigger any topic call"

    llm.replies_json(CARDS, usage=READ_CACHE).replies_json(CARDS, usage=READ_CACHE)
    client.post(f"/api/jobs/{job_id}/generate")
    # One plan, then a lesson and a set of cards for each of the two topics.
    assert len(llm.requests) == 5
    assert len(llm.calls_for("cards")) == 2
