PLAN = {
    "topics": [
        {
            "topic_id": "glycolysis",
            "path": "Biology::Metabolism::Glycolysis",
            "difficulty": "hard",
            "rationale": "Dense multi-step pathway with regulated enzymes.",
            "note_type": "cloze",
            "proposed_card_count": 6,
        },
        {
            "topic_id": "cell-basics",
            "path": "Biology::Cell Structure",
            "difficulty": "easy",
            "rationale": "Straightforward definitions.",
            "note_type": "basic",
            "proposed_card_count": 2,
        },
    ]
}


def upload(client, text=b"Glycolysis occurs in the cytosol."):
    return client.post(
        "/api/jobs", files={"file": ("lecture.txt", text, "text/plain")}
    ).json()["job_id"]


def test_planning_a_job_produces_a_deck_plan(client, claude):
    claude.replies_json(PLAN)
    job_id = upload(client)

    response = client.post(f"/api/jobs/{job_id}/plan")

    assert response.status_code == 200
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "plan_ready"

    topics = job["plan"]["topics"]
    assert [t["path"] for t in topics] == [
        "Biology::Metabolism::Glycolysis",
        "Biology::Cell Structure",
    ]
    assert topics[0]["difficulty"] == "hard"
    assert topics[0]["proposed_card_count"] == 6


def test_the_plan_request_constrains_the_response_to_a_non_recursive_schema(client, claude):
    claude.replies_json(PLAN)
    job_id = upload(client)

    client.post(f"/api/jobs/{job_id}/plan")

    sent = claude.requests[0]
    assert sent["model"] == "claude-opus-5"

    schema = sent["output_config"]["format"]["schema"]
    # Structured outputs reject recursive schemas outright, so the topic tree is
    # a flat array whose hierarchy lives in a "::" path string.
    assert schema["properties"]["topics"]["type"] == "array"
    topic = schema["properties"]["topics"]["items"]
    assert topic["properties"]["path"]["type"] == "string"
    assert "$ref" not in json_dumps(topic)
    assert topic["additionalProperties"] is False

    # The document must be the first thing in the user message, so the same
    # cached prefix can serve the generation pass.
    assert sent["messages"][0]["content"][0]["type"] == "document"


def json_dumps(value):
    import json

    return json.dumps(value)
