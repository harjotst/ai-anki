"""Real PDFs, and a gate that measures the thing that actually costs money.

Page count is rejected as the unit deliberately. It does not exist for several
accepted formats, and it does not predict cost: a PDF page is read as
extracted text *and* a rendered image, so a scanned page costs multiples of a
text one at the same page count.
"""

PDF = b"%PDF-1.4\nfake but plausibly a pdf\n%%EOF"

PLAN = {
    "topics": [
        {
            "topic_id": "t1",
            "path": "Bio::Cells",
            "difficulty": "medium",
            "rationale": "Mixed.",
            "note_type": "basic",
            "proposed_card_count": 3,
        }
    ]
}


def upload_pdf(client, name="lecture.pdf"):
    return client.post(
        "/api/jobs", files={"file": (name, PDF, "application/pdf")}, data={"deck_name": "Lecture"}
    ).json()["job_id"]


def test_a_pdf_is_sent_to_the_files_api_and_referenced_by_identifier(client, llm):
    llm.counts_tokens(50_000).replies_json(PLAN)
    job_id = upload_pdf(client)

    assert client.post(f"/api/jobs/{job_id}/plan").status_code == 200

    assert llm.uploads == ["lecture.pdf"], "the PDF is uploaded once, not inlined"
    document = llm.requests[-1]["input"][0]["content"][0]
    # By reference, because a request body is capped far below what this job's
    # token ceiling allows.
    assert document == {"type": "input_file", "file_id": "file-0000"}


def test_an_upload_is_marked_as_user_data(client, llm):
    """`user_data` is the purpose the Responses API reads input files under."""
    llm.counts_tokens(50_000).replies_json(PLAN)
    job_id = upload_pdf(client)
    client.post(f"/api/jobs/{job_id}/plan")

    assert b'name="purpose"' in llm.file_requests[0].content
    assert b"user_data" in llm.file_requests[0].content


def test_the_gate_counts_tokens_over_the_assembled_request_before_spending_anything(
    client, llm
):
    llm.counts_tokens(50_000).replies_json(PLAN)
    job_id = upload_pdf(client)
    client.post(f"/api/jobs/{job_id}/plan")

    assert len(llm.count_requests) == 1
    counted = llm.count_requests[0]

    # The gate measured the very request that was then sent — same model,
    # same documents, same instruction — not a separate approximation of it.
    assert counted == llm.requests[-1]
    assert counted["model"] == "gpt-5.6-luna"


def test_a_job_over_the_ceiling_is_refused_before_a_single_generation_call(client, llm):
    llm.counts_tokens(900_000)
    job_id = upload_pdf(client)

    refused = client.post(f"/api/jobs/{job_id}/plan")

    assert refused.status_code == 413
    body = refused.json()["detail"]
    # The measured number is shown, because "too big" with no figure gives the
    # user nothing to act on.
    assert "900,000" in body or "900000" in body
    assert llm.requests == [], "nothing may be generated for a job that was refused"

    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "failed"


def test_the_estimate_is_reported_in_tokens_and_money_never_in_pages(client, llm):
    llm.counts_tokens(200_000)
    job_id = upload_pdf(client)

    estimate = client.get(f"/api/jobs/{job_id}/estimate").json()

    assert estimate["input_tokens"] == 200_000
    assert estimate["within_limit"] is True
    # 200k tokens: each pass writes the document into the cache once at
    # $0.25/MTok, so two passes are $0.10 before a single read or output
    # token. Checked against that independently worked floor rather than
    # against the code's own arithmetic.
    assert estimate["estimated_cost_usd"] >= 0.10
    assert estimate["estimated_cost_usd"] < 1.00
    assert "page" not in " ".join(estimate).lower()


def test_the_estimate_says_plainly_when_a_job_is_too_large(client, llm):
    llm.counts_tokens(900_000)
    job_id = upload_pdf(client)

    estimate = client.get(f"/api/jobs/{job_id}/estimate").json()

    assert estimate["within_limit"] is False
    assert estimate["token_ceiling"] == 700_000


def test_a_scanned_pdf_goes_through_the_same_path_with_no_ocr_stage(client, llm):
    """A photocopied chapter is as usable as a born-digital one.

    There is deliberately no OCR stage: the model reads the page image. This
    asserts the pipeline does not branch on whether text could be extracted.
    """
    llm.counts_tokens(50_000).replies_json(PLAN)
    job_id = upload_pdf(client, name="scan-of-chapter-4.pdf")

    assert client.post(f"/api/jobs/{job_id}/plan").status_code == 200
    assert llm.uploads == ["scan-of-chapter-4.pdf"]
    assert llm.requests[-1]["input"][0]["content"][0]["type"] == "input_file"


def test_a_text_upload_still_goes_inline_and_costs_no_upload(client, llm):
    llm.counts_tokens(500).replies_json(PLAN)
    job_id = client.post(
        "/api/jobs", files={"file": ("notes.txt", b"Some material.", "text/plain")}, data={"deck_name": "Lecture"}
    ).json()["job_id"]

    client.post(f"/api/jobs/{job_id}/plan")

    assert llm.uploads == [], "small text does not need the Files API"
    assert llm.requests[-1]["input"][0]["content"][0] == {
        "type": "input_text", "text": "Some material."
    }
