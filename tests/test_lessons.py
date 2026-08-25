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
        {
            "question": "Why does blocking transpeptidase kill a growing cell but spare a resting one?",
            "answer": "Only growing cells rebuild wall; without cross-links the new wall cannot hold pressure.",
        }
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


# --- reading it while the rest is still being written --------------------


def test_a_lesson_is_readable_before_the_whole_job_has_finished(client, claude):
    """Ten minutes of a blank screen is the failure this prevents.

    Lessons are the slowest part of a job — around 4,000 output tokens each
    against 400 for a set of cards, and output is what wall-clock is made of.
    Making somebody wait for all of them before reading any is the difference
    between a tool they use and a tab they close.
    """
    import threading

    from tests.test_generation import CELL_CARDS

    job_id = planned(client, claude)
    # Every cards call hangs, so the job is still going while we look.
    claude.answers(lesson=LESSON, cards=CELL_CARDS, pause={"cards": 1.5})

    running = threading.Thread(
        target=lambda: client.post(f"/api/jobs/{job_id}/generate"), daemon=True
    )
    running.start()
    assert claude.wait_for_paused_call(timeout=5), "the first cards call should be open"

    mid_run = client.get(f"/api/jobs/{job_id}/lessons").json()["lessons"]
    assert len(mid_run) >= 1, "the first lesson is committed before its cards are asked for"
    assert mid_run[0]["in_one_line"] == LESSON["in_one_line"]
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "generating"

    running.join(timeout=30)


def test_a_lesson_landing_is_reported_on_the_progress_log(client, claude):
    """A client that was never connected can still reconstruct the run, so a
    lesson arriving has to be an event rather than only a row."""
    job_id = planned(client, claude)
    teach_and_generate(client, claude, job_id)

    from tests.test_live_progress import sse_events

    taught = [
        event
        for event in sse_events(client.get(f"/api/jobs/{job_id}/events"))
        if event.event == "lesson"
    ]

    assert {event.data["topic_id"] for event in taught} == {"glycolysis", "cell-basics"}
    assert all(event.data["path"] for event in taught)
    # Enough to show in a list without fetching the whole lesson, which is what
    # a screen watching a run actually needs.
    assert all(event.data["in_one_line"] for event in taught)


# --- text that survived a JSON encoder twice -----------------------------


def test_escape_sequences_the_model_double_escaped_are_decoded():
    """Seen on a real run: `\\u2014` and `\\r\\n` rendered on screen as text.

    In JSON an em dash may be written literally or as a `\\u2014` escape, and
    the decoder resolves the latter. For the escape to survive into the string
    the model must have escaped the backslash as well — it is writing JSON
    about JSON. Asking it not to in the prompt would help and would not be
    reliable, and this has to be reliable: the alternative is `\\u2014` on the
    page of every lesson that wanted a dash.
    """
    from app.lessons import readable

    assert readable("arbitrary \\u2014 it falls out") == "arbitrary — it falls out"
    assert readable("first.\\r\\nSecond.") == "first.\nSecond."
    assert readable("one\\ntwo") == "one\ntwo"
    assert readable("50 \\u00b5mol") == "50 µmol"


def test_text_that_was_already_correct_is_left_alone():
    from app.lessons import readable

    for untouched in ["a plain sentence", "an em dash — already decoded", "5 < 10", ""]:
        assert readable(untouched) == untouched


def test_a_lesson_is_cleaned_before_it_is_stored(client, claude):
    """Cleaned on the way in, not on the way out. Every reader would otherwise
    have to remember to do it, and one of them will not."""
    job_id = planned(client, claude)
    claude.answers(
        lesson={
            **LESSON,
            "in_one_line": "Glycolysis \\u2014 the anaerobic route.",
            "sections": [
                {"heading": "One", "body": "First.\\r\\nSecond.", "builds_on": None}
            ],
        },
        cards={"cards": []},
    )
    client.post(f"/api/jobs/{job_id}/generate")

    lesson = client.get(f"/api/jobs/{job_id}/topics/glycolysis/lesson").json()

    assert lesson["in_one_line"] == "Glycolysis — the anaerobic route."
    assert lesson["sections"][0]["body"] == "First.\nSecond."
