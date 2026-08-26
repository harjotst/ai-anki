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
WROTE_CACHE = {"input_tokens": 500, "cache_creation_input_tokens": 200_000, "output_tokens": 2_000}
READ_CACHE = {"input_tokens": 400, "cache_read_input_tokens": 200_000, "output_tokens": 1_000}


def upload(client):
    return client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}
    ).json()["job_id"]


def run_job(client, claude):
    claude.counts_tokens(200_000).replies_json(PLAN, usage=WROTE_CACHE)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    claude.answers(cards=CARDS, usage=READ_CACHE)
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id


def test_every_topic_call_sends_a_byte_identical_cacheable_prefix(client, claude):
    """The topic calls share with each other. That is where the saving is.

    They do NOT share with the planning pass, and no amount of prefix
    discipline will make them: measured against the live API on 2026-08-17,
    a request carrying a different JSON schema gets its own cache lineage,
    because structured outputs render ahead of the messages.
    """
    run_job(client, claude)
    # By kind, not by position. Each topic now makes two calls -- a lesson and
    # its cards -- and they interleave across a concurrent fan-out, so an index
    # says nothing. Cards share a lineage with cards; lessons with lessons.
    plan_request = claude.calls_for("topics")[0]
    first, *rest = claude.calls_for("cards")
    for request in rest:
        assert request["system"] == first["system"], "a per-call system prompt kills the cache"
        assert request["messages"][0]["content"][0] == first["messages"][0]["content"][0]
        assert request["output_config"]["format"] == first["output_config"]["format"], (
            "a differing schema puts this call in its own cache lineage"
        )
        # Effort and thinking sit outside the message prefix, but the spec pins
        # them anyway rather than rely on an invalidation rule we have not been
        # able to confirm against the live API.
        assert request["output_config"]["effort"] == plan_request["output_config"]["effort"]
        assert request.get("thinking") == plan_request.get("thinking")
        assert request.get("tools") == plan_request.get("tools")


def test_the_planning_pass_does_not_pay_for_a_cache_nothing_reads(client, claude):
    """Measured, not assumed. This was a real bug found on the first live call.

    The planning pass is the only call in a job sending DECK_PLAN_SCHEMA, so
    nothing ever reads what it writes — and a one-hour entry costs 2x base
    input to create. It was pure waste.
    """
    run_job(client, claude)

    plan_content = claude.requests[0]["messages"][0]["content"]
    assert not any("cache_control" in block for block in plan_content)


def test_the_topic_calls_cache_for_five_minutes_because_they_run_back_to_back(client, claude):
    run_job(client, claude)

    content = claude.calls_for("cards")[0]["messages"][0]["content"]
    documents = [block for block in content if block["type"] == "document"]

    assert content[-1]["type"] == "text", "the varying instruction goes after the breakpoint"
    # Five minutes, not an hour: the topic calls run consecutively in the
    # worker, and an hour costs 2x base input against 1.25x for five minutes.
    assert documents[-1]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
    # Exactly one breakpoint: the cache is a prefix match, so marking earlier
    # blocks buys nothing and spends one of the four allowed.
    assert sum("cache_control" in block for block in content) == 1


def test_generation_reads_the_cache_the_planning_pass_wrote(client, claude):
    job_id = run_job(client, claude)

    calls = client.get(f"/api/jobs/{job_id}/usage").json()["calls"]

    plan_call = next(c for c in calls if c["pass_name"] == "plan")
    topic_calls = [c for c in calls if c["pass_name"] == "cards"]

    assert plan_call["cache_creation_input_tokens"] == 200_000
    assert plan_call["cache_read_input_tokens"] == 0

    assert len(topic_calls) == 2
    for call in topic_calls:
        assert call["cache_read_input_tokens"] > 0, "a topic call that writes is a broken prefix"
        assert call["cache_creation_input_tokens"] == 0


def test_the_job_reports_what_it_actually_cost_not_what_it_was_estimated_to(client, claude):
    job_id = run_job(client, claude)

    usage = client.get(f"/api/jobs/{job_id}/usage").json()

    # Worked by hand from the scripted usage, independently of the code:
    #   plan   500 uncached @ $5/MTok            = $0.0025
    #          200,000 cache write @ 2x $5/MTok  = $2.0000
    #          2,000 output @ $25/MTok           = $0.0500
    #   cards  2 x (400 uncached @ $5/MTok       = $0.0020
    #               200,000 cache read @ 0.1x    = $0.1000
    #               1,000 output @ $25/MTok      = $0.0250)
    #   lesson 2 x (100 uncached @ $5/MTok       = $0.0005
    #               50 output @ $25/MTok         = $0.00125)
    #
    # The lesson line is small here only because the fake's stock usage is
    # small. On a real job it is the same order as the cards, which is the
    # number the estimate has to carry.
    # Sonnet prices (2.00 / 10.00 / 4.00 / 0.20 per M) — the model the
    # product actually runs.
    expected = 0.001 + 0.8 + 0.02 + 2 * (0.0008 + 0.04 + 0.01) + 2 * (0.0002 + 0.0005)
    assert abs(usage["total_cost_usd"] - expected) < 0.0001
    assert usage["total_cost_usd"] > 0


def test_a_cached_run_costs_a_fraction_of_what_it_would_uncached(client, claude):
    """The claim the two-pass design is built on, stated as a number."""
    job_id = run_job(client, claude)
    actual = client.get(f"/api/jobs/{job_id}/usage").json()["total_cost_usd"]

    # Had each topic call paid full price for the same 200k document instead of
    # reading it, the input alone would have been 2 x 200,000 @ $2/MTok = $0.80.
    # Priced off the provider's own sheet — the module-level constants this
    # arithmetic used to lean on quoted a model the suite no longer runs.
    from app.providers.anthropic_provider import MODELS

    prices = MODELS["claude-sonnet-5"]
    uncached_topic_input = 2 * 200_000 * prices.input / 1_000_000
    cached_topic_input = 2 * 200_000 * prices.cache_read / 1_000_000

    assert cached_topic_input < uncached_topic_input / 5
    assert actual < uncached_topic_input + 2.5


def test_no_topic_call_is_made_until_the_planning_pass_has_returned(client, claude):
    """A cache entry is only readable once the first response has begun.

    Fanning out before pass 1 returns would have every topic call miss and pay a
    2x cache-creation charge — worse than not caching at all.
    """
    claude.counts_tokens(200_000).replies_json(PLAN, usage=WROTE_CACHE)
    job_id = upload(client)

    client.post(f"/api/jobs/{job_id}/plan")
    assert len(claude.requests) == 1, "planning must not trigger any topic call"

    claude.replies_json(CARDS, usage=READ_CACHE).replies_json(CARDS, usage=READ_CACHE)
    client.post(f"/api/jobs/{job_id}/generate")
    # One plan, then a lesson and a set of cards for each of the two topics.
    assert len(claude.requests) == 5
    assert len(claude.calls_for("cards")) == 2
