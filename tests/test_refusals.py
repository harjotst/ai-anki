from tests.test_planning import PLAN, upload


def test_a_safety_refusal_fails_the_job_rather_than_crashing(client, claude):
    # Opus 5 returns refusals as HTTP 200 with an empty content array. Reading
    # content[0] blind would raise; a student uploading pharmacology or
    # microbiology notes can plausibly trigger this.
    claude.refuses(category="bio")
    job_id = upload(client)

    response = client.post(f"/api/jobs/{job_id}/plan")

    assert response.status_code == 422
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "failed"
    assert "declined" in job["error"].lower()
    assert "bio" in job["error"]


def test_a_truncated_response_fails_the_job_rather_than_parsing_half_the_json(client, claude):
    claude.replies('{"topics": [{"topic_id": "glyc', stop_reason="max_tokens")
    job_id = upload(client)

    response = client.post(f"/api/jobs/{job_id}/plan")

    assert response.status_code == 422
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "failed"
    assert "max_tokens" in job["error"]


def test_the_fallback_opt_in_is_no_longer_sent_where_it_would_be_refused(client, claude):
    """Sonnet 5 rejects the `fallbacks` parameter outright — the whole request
    400s (observed live 2026-08-26), which is a far worse outcome than the
    occasional unrescued refusal the opt-in existed to soften. Opus still
    opts in; test_providers pins both directions.
    """
    claude.replies_json(PLAN)
    job_id = upload(client)

    client.post(f"/api/jobs/{job_id}/plan")

    assert "fallbacks" not in claude.requests[0]
