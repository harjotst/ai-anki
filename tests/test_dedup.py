"""Stopping the same fact becoming three cards.

Parallel topic calls each see the whole corpus and none of them sees what the
others are writing, so overlap is the normal outcome on a multi-file job rather
than an edge case. Anki dedups on exact first-field match within one notetype,
so a paraphrase is invisible to it — the user simply reviews the same fact three
times, forever, in three different subdecks.
"""

from app import dedup

PLAN = {
    "topics": [
        {
            "topic_id": "resting",
            "path": "Neuro::Resting Potential",
            "difficulty": "hard",
            "rationale": "Dense.",
            "note_type": "basic",
            "proposed_card_count": 2,
            "claims": ["The resting membrane potential is about -70 mV."],
        },
        {
            "topic_id": "channels",
            "path": "Neuro::Ion Channels",
            "difficulty": "hard",
            "rationale": "Dense.",
            "note_type": "basic",
            "proposed_card_count": 2,
            "claims": ["Voltage-gated sodium channels open at threshold."],
        },
    ]
}


def card(front, back="."):
    return {"note_type": "basic", "front": front, "back": back, "source_page": 1,
            "existing_card_id": None}


def run(client, claude, first, second):
    claude.counts_tokens(1000).replies_json(PLAN)
    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")
    claude.replies_json({"cards": first}).replies_json({"cards": second})
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id


def test_the_plan_gives_each_topic_claims_it_alone_owns(client, claude):
    claude.counts_tokens(1000).replies_json(PLAN)
    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")

    schema = claude.requests[0]["output_config"]["format"]["schema"]
    topic = schema["properties"]["topics"]["items"]
    assert "claims" in topic["properties"]
    # Partitioning the material is what prevents the overlap; catching
    # duplicates afterwards is the safety net, not the mechanism.
    assert "claims" in topic["required"]


def test_each_topic_call_is_told_what_the_other_topics_own(client, claude):
    run(client, claude, [card("Q1?")], [card("Q2?")])

    channels_instruction = claude.requests[-1]["messages"][0]["content"][-1]["text"]
    assert "Neuro::Resting Potential" in channels_instruction
    assert "Voltage-gated sodium channels open at threshold." in channels_instruction


def test_an_exact_duplicate_across_topics_is_flagged_not_silently_dropped(client, claude):
    job_id = run(
        client,
        claude,
        [card("What is the resting membrane potential?", "About -70 mV.")],
        [card("What is the resting membrane potential?", "About -70 mV.")],
    )

    cards = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]
    flagged = [c for c in cards if c["duplicate_of"]]

    assert len(flagged) == 1, "the later one is flagged, the first is kept"
    # Surfaced rather than deleted: the user decides, because the tool cannot
    # tell a genuine duplicate from two questions that merely read alike.
    assert len(cards) == 2


def test_the_kept_copy_is_the_one_in_the_more_specific_topic(client, claude):
    job_id = run(
        client,
        claude,
        [card("What is the resting membrane potential?", "-70 mV.")],
        [card("What is the resting membrane potential?", "-70 mV.")],
    )

    cards = {c["deck_path"]: c for c in client.get(f"/api/jobs/{job_id}/cards").json()["cards"]}
    assert cards["Neuro::Resting Potential"]["duplicate_of"] is None


def test_normalisation_sees_through_formatting_but_not_through_meaning():
    assert dedup.same_question("What is the RMP?", "what is the rmp?")
    assert dedup.same_question("What is  the RMP?", "<b>What is the RMP?</b>")
    assert not dedup.same_question(
        "What is the resting potential?", "Which ion drives repolarisation?"
    )


def test_a_deck_with_no_overlap_flags_nothing(client, claude):
    job_id = run(
        client,
        claude,
        [card("What is the resting membrane potential?")],
        [card("When do voltage-gated sodium channels open?")],
    )

    cards = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]
    assert all(c["duplicate_of"] is None for c in cards)


def test_the_download_page_says_to_check_for_overlap_with_cards_already_owned(client, claude):
    job_id = run(client, claude, [card("Q1?")], [card("Q2?")])

    guidance = client.get(f"/api/jobs/{job_id}/download-info").json()

    # We can only see inside this job. Overlap with the user's existing 14,000
    # notes is theirs to check, and Anki has a tool for it.
    assert "duplicate" in guidance["duplicate_advice"].lower()
