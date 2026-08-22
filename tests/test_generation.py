from tests.test_planning import PLAN, upload

GLYCOLYSIS_CARDS = {
    "cards": [
        {
            "note_type": "cloze",
            "front": "Glycolysis occurs in the {{c1::cytosol}}.",
            "back": "Ten enzymatic steps.",
        },
        {
            "note_type": "basic",
            "front": "What is the rate-limiting enzyme of glycolysis?",
            "back": "Phosphofructokinase-1.",
        },
    ]
}

CELL_CARDS = {
    "cards": [
        {
            "note_type": "basic",
            "front": "What organelle produces most ATP?",
            "back": "The mitochondrion.",
        }
    ]
}


def planned_job(client, claude):
    claude.replies_json(PLAN)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    return job_id


def test_generation_produces_cards_for_every_topic(client, claude):
    job_id = planned_job(client, claude)
    claude.replies_json(GLYCOLYSIS_CARDS).replies_json(CELL_CARDS)

    response = client.post(f"/api/jobs/{job_id}/generate")

    assert response.status_code == 200
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "complete"

    cards = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]
    assert len(cards) == 3
    assert cards[0]["deck_path"] == "Biology::Metabolism::Glycolysis"
    assert cards[0]["note_type"] == "cloze"
    assert cards[2]["deck_path"] == "Biology::Cell Structure"
    # A stable identifier per card is what later makes re-import non-destructive.
    assert len({c["card_uuid"] for c in cards}) == 3


def test_each_topic_call_reuses_the_other_topic_calls_prefix(client, claude):
    job_id = planned_job(client, claude)
    claude.replies_json(GLYCOLYSIS_CARDS).replies_json(CELL_CARDS)

    client.post(f"/api/jobs/{job_id}/generate")

    # The cards calls, asked for by kind. Each topic also makes a lesson call,
    # which shares a lineage with the other lessons and not with these.
    topic_requests = claude.calls_for("cards")
    assert len(topic_requests) == 2

    first, *rest = topic_requests
    for request in rest:
        # A cache entry is keyed on the bytes up to the breakpoint. The topic
        # calls share one prefix with EACH OTHER — the first writes it, the
        # rest read it. They do not share with the planning pass: measured on
        # 2026-08-17, a different JSON schema gets its own cache lineage.
        assert request["system"] == first["system"]
        assert request["messages"][0]["content"][0] == first["messages"][0]["content"][0]

    # The pass-specific instruction goes after the documents, never in system.
    glycolysis_instruction = topic_requests[0]["messages"][0]["content"][-1]["text"]
    assert "Biology::Metabolism::Glycolysis" in glycolysis_instruction
    assert "6" in glycolysis_instruction
