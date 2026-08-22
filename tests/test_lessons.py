"""Teaching the material, not only drilling it.

A deck of 164 cards handed to somebody who has not understood the material is
worse than useless: they drill wrong models into long-term memory and the
scheduler faithfully keeps them there. The lesson is what the cards are meant to
reinforce, so it is generated first and it is the thing the user reads.

Pass 1 already produces a syllabus — topics in dependency order, each with the
claims it exclusively owns — and until now everything except the card counts was
thrown away. The lesson pass is what reads it.
"""

from tests.test_planning import PLAN, upload

LESSON = {
    "in_one_line": "Glycolysis splits glucose into two pyruvate, netting ATP and NADH.",
    "why_it_matters": (
        "It is the only pathway that yields ATP without oxygen, which is what makes "
        "it the fallback every tissue reaches for under load."
    ),
    "sections": [
        {
            "heading": "The investment phase",
            "body": "Two ATP are spent before any are made, which is why...",
            "builds_on": None,
        },
        {
            "heading": "The payoff phase",
            "body": "Four ATP are produced, so the net is two.",
            "builds_on": "The investment phase",
        },
    ],
    "worked_example": {
        "problem": "One glucose enters glycolysis. How much ATP leaves?",
        "walkthrough": "Two spent, four made, so a net of two.",
    },
    "misconceptions": [
        {
            "belief": "Glycolysis produces four ATP.",
            "why_it_is_wrong": (
                "Four are produced but two were spent up front, so the number worth "
                "remembering is the net of two."
            ),
        }
    ],
    "check_yourself": [
        "Why is the net ATP yield two rather than four?",
        "What makes glycolysis usable without oxygen?",
    ],
}


def lesson_for(topic_id="cells"):
    return {**LESSON, "topic_id": topic_id}


def planned(client, claude, plan=PLAN):
    claude.replies_json(plan)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    return job_id


def teach_and_generate(client, claude, job_id, plan=PLAN):
    """Answer every lesson call and every cards call, then run the job.

    Keyed on what each call asks for rather than on arrival order, because
    topics fan out concurrently and each makes two calls -- so the order six
    calls across three topics arrive in is not something a test should predict.
    """
    from tests.test_generation import CELL_CARDS

    claude.answers(lesson=LESSON, cards=CELL_CARDS)
    return client.post(f"/api/jobs/{job_id}/generate")


# --- the request ---------------------------------------------------------


def test_a_lesson_is_written_for_every_topic_before_its_cards(client, claude):
    """Order is the point, not a detail.

    Cards reinforce comprehension; they do not create it. Generating them first
    would make the lesson a footnote to a deck the user already has.
    """
    job_id = planned(client, claude)

    teach_and_generate(client, claude, job_id)

    schemas = [
        request["output_config"]["format"]["schema"]["properties"].keys()
        for request in claude.requests[1:]
    ]
    assert "sections" in list(schemas[0]), "the lesson call comes first"
    assert "cards" in list(schemas[1])


def test_the_lesson_is_told_which_claims_this_topic_owns(client, claude):
    """The same partition the cards use.

    A lesson that wanders into a neighbouring topic teaches the same thing
    twice, in two places, and the user meets it as a contradiction rather than
    as repetition.
    """
    job_id = planned(client, claude)
    teach_and_generate(client, claude, job_id)

    instruction = claude.requests[1]["messages"][0]["content"][-1]["text"]
    assert "Biology::Metabolism::Glycolysis" in instruction
    assert "teach" in instruction.lower()


def test_lesson_calls_share_a_cache_with_each_other_and_not_with_the_cards(client, claude):
    """Measured against the live API on 2026-08-17: a request carrying a
    different JSON schema gets its own cache lineage, because structured
    outputs render ahead of the messages.

    So the lessons share a prefix among themselves and the cards share one among
    themselves, and neither can read the other's. The five-minute lifetime is
    right for both: they run back to back with no human pause between them, and
    an hour costs 2x base input against 1.25x for five minutes.
    """
    job_id = planned(client, claude)
    teach_and_generate(client, claude, job_id)

    lesson_call, cards_call = claude.requests[1], claude.requests[2]
    marker = lesson_call["messages"][0]["content"][0].get("cache_control")
    assert marker == {"type": "ephemeral", "ttl": "5m"}
    assert cards_call["messages"][0]["content"][0].get("cache_control") == marker
    # Same documents, different schema -- which is exactly the pair that does
    # NOT share, and the reason each pass needs its own pacesetter.
    assert (
        lesson_call["output_config"]["format"]["schema"]
        != cards_call["output_config"]["format"]["schema"]
    )


# --- what comes back -----------------------------------------------------


def test_the_lesson_is_kept_and_read_back_per_topic(client, claude):
    job_id = planned(client, claude)
    teach_and_generate(client, claude, job_id)

    lesson = client.get(f"/api/jobs/{job_id}/topics/glycolysis/lesson").json()

    assert lesson["in_one_line"] == LESSON["in_one_line"]
    assert [s["heading"] for s in lesson["sections"]] == [
        "The investment phase",
        "The payoff phase",
    ]
    assert lesson["misconceptions"][0]["belief"] == "Glycolysis produces four ATP."
    assert lesson["deck_path"] == "Biology::Metabolism::Glycolysis"


def test_a_topic_with_no_lesson_yet_says_so_rather_than_failing(client, claude):
    job_id = planned(client, claude)

    missing = client.get(f"/api/jobs/{job_id}/topics/glycolysis/lesson")

    assert missing.status_code == 404


def test_the_lessons_for_a_whole_job_are_listed_in_plan_order(client, claude):
    """Plan order, not the order they finished in.

    Topics are taught in dependency order and they generate concurrently, so
    the order the calls came back in carries no meaning at all — and a reader
    handed section three before section one is a reader who gives up.
    """
    ordered = {
        "topics": [
            {**topic, "topic_id": f"t{index}", "path": f"Bio::Step {index}"}
            for index, topic in enumerate(
                [PLAN["topics"][0], PLAN["topics"][1], PLAN["topics"][0]]
            )
        ]
    }

    job_id = planned(client, claude, plan=ordered)
    teach_and_generate(client, claude, job_id, plan=ordered)

    listed = client.get(f"/api/jobs/{job_id}/lessons").json()["lessons"]

    assert [entry["topic_id"] for entry in listed] == ["t0", "t1", "t2"]


def test_a_lesson_someone_else_owns_is_not_readable(boot, claude):
    from tests.conftest import SOMEBODY_ELSE

    with boot() as machine:
        job_id = planned(machine, claude)
        teach_and_generate(machine, claude, job_id)

        machine.sign_in_as(SOMEBODY_ELSE)

        assert machine.get(f"/api/jobs/{job_id}/lessons").status_code == 404
        assert machine.get(f"/api/jobs/{job_id}/topics/glycolysis/lesson").status_code == 404


# --- cost ----------------------------------------------------------------


def test_a_lesson_is_billed_and_attributed_like_any_other_call(client, claude):
    """Lessons roughly double what a job costs, so they cannot be invisible in
    the accounting -- the estimate before approval is the moment the user
    decides whether to spend it."""
    from tests.test_generation import CELL_CARDS

    job_id = planned(client, claude)
    claude.answers(
        lesson=LESSON,
        cards=CELL_CARDS,
        usage={"input_tokens": 20, "cache_creation_input_tokens": 4000, "output_tokens": 900},
    )
    client.post(f"/api/jobs/{job_id}/generate")

    calls = client.get(f"/api/jobs/{job_id}/usage").json()["calls"]
    taught = [call for call in calls if call["pass_name"] == "lesson"]

    assert {call["topic_id"] for call in taught} == {"glycolysis", "cell-basics"}
    assert all(call["cost_usd"] > 0 for call in taught)
    # And it is a real share of the bill rather than a rounding error, which is
    # what the estimate has to carry.
    total = sum(call["cost_usd"] for call in calls)
    assert sum(call["cost_usd"] for call in taught) > total * 0.2


def test_the_estimate_prices_the_lesson_pass_as_well_as_the_cards(client, claude):
    """A quote that ignores half the work is a quote that will be wrong by
    half, at the exact moment somebody is deciding whether to spend it."""
    from app import ingestion

    job_id = planned(client, claude)
    claude.counts_tokens(200_000)

    estimate = client.get(f"/api/jobs/{job_id}/estimate").json()

    assert estimate["estimated_cost_usd"] == ingestion.estimate_cost(
        200_000, topics=2, passes_per_topic=2
    )
    assert estimate["estimated_cost_usd"] > ingestion.estimate_cost(
        200_000, topics=2, passes_per_topic=1
    )
