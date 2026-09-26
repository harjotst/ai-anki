from tests.test_planning import PLAN, upload


def test_a_safety_refusal_fails_the_job_rather_than_crashing(client, llm):
    # A refusal arrives as HTTP 200 with a refusal part and no text. Parsing
    # the output blind would raise; a student uploading pharmacology or
    # microbiology notes can plausibly trigger this.
    llm.refuses("I can't help with that.")
    job_id = upload(client)

    response = client.post(f"/api/jobs/{job_id}/plan")

    assert response.status_code == 422
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "failed"
    assert "declined" in job["error"].lower()
    assert "I can't help with that." in job["error"], "the model's own reason is kept"


def test_a_truncated_response_fails_the_job_rather_than_parsing_half_the_json(client, llm):
    llm.replies('{"topics": [{"topic_id": "glyc', truncated=True)
    job_id = upload(client)

    response = client.post(f"/api/jobs/{job_id}/plan")

    assert response.status_code == 422
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "failed"
    assert "max_output_tokens" in job["error"]
