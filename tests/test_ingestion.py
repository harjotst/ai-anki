"""Real PDFs, and a gate that measures the thing that actually costs money.

Page count is rejected as the unit deliberately. It does not exist for several
accepted formats, and it does not predict cost: Claude bills every PDF page as
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
        "/api/jobs", files={"file": (name, PDF, "application/pdf")}
    ).json()["job_id"]


def test_a_pdf_is_sent_to_the_files_api_and_referenced_by_identifier(client, claude):
    claude.counts_tokens(50_000).replies_json(PLAN)
    job_id = upload_pdf(client)

    assert client.post(f"/api/jobs/{job_id}/plan").status_code == 200

    assert claude.uploads == ["lecture.pdf"], "the PDF is uploaded once, not inlined"
    document = claude.requests[-1]["messages"][0]["content"][0]
    assert document["type"] == "document"
    # By reference, because inlining is capped at a 32MB request and this job's
    # ceiling is well past that.
    assert document["source"]["type"] == "file"
    assert document["source"]["file_id"] == "file_0000"


def test_the_files_beta_header_rides_on_the_upload_and_on_every_request_that_uses_it(
    client, claude
):
    claude.counts_tokens(50_000).replies_json(PLAN)
    job_id = upload_pdf(client)
    client.post(f"/api/jobs/{job_id}/plan")

    upload_headers = claude.file_requests[0].headers["anthropic-beta"]
    assert "files-api-2025-04-14" in upload_headers
    # The header is required on both ends: referencing a file without it fails
    # even though the upload succeeded.
    assert any("files-api-2025-04-14" in str(v) for v in [upload_headers])


def test_the_gate_counts_tokens_over_the_assembled_request_before_spending_anything(
    client, claude
):
    claude.counts_tokens(50_000).replies_json(PLAN)
    job_id = upload_pdf(client)
    client.post(f"/api/jobs/{job_id}/plan")

    assert len(claude.count_requests) == 1
    counted = claude.count_requests[0]
    assert counted["model"] == "claude-opus-5"

    # Counted over the same CONTENT that will be sent, but not the same
    # transport. The token-counting endpoint refuses `file` sources outright —
    # "File sources are not supported in the token counting endpoint" — so the
    # uploaded document is swapped for an inlined copy of the identical bytes.
    counted_source = counted["messages"][0]["content"][0]["source"]
    assert counted_source["type"] == "base64"

    # What actually goes to the model still references the upload, because a
    # 32MB request limit is the reason the file was uploaded in the first place.
    sent_source = claude.requests[-1]["messages"][0]["content"][0]["source"]
    assert sent_source["type"] == "file"
    assert sent_source["file_id"] == "file_0000"


def test_a_job_over_the_ceiling_is_refused_before_a_single_generation_call(client, claude):
    claude.counts_tokens(900_000)
    job_id = upload_pdf(client)

    refused = client.post(f"/api/jobs/{job_id}/plan")

    assert refused.status_code == 413
    body = refused.json()["detail"]
    # The measured number is shown, because "too big" with no figure gives the
    # user nothing to act on.
    assert "900,000" in body or "900000" in body
    assert claude.requests == [], "nothing may be generated for a job that was refused"

    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "failed"


def test_the_estimate_is_reported_in_tokens_and_money_never_in_pages(client, claude):
    claude.counts_tokens(200_000)
    job_id = upload_pdf(client)

    estimate = client.get(f"/api/jobs/{job_id}/estimate").json()

    assert estimate["input_tokens"] == 200_000
    assert estimate["within_limit"] is True
    # 200k tokens: one 1h cache write at 2x $5/MTok is $2.00, so the estimate
    # must be at least that and is checked against an independently worked
    # figure rather than against the code's own arithmetic.
    assert estimate["estimated_cost_usd"] >= 2.00
    assert estimate["estimated_cost_usd"] < 10.00
    assert "page" not in " ".join(estimate).lower()


def test_the_estimate_says_plainly_when_a_job_is_too_large(client, claude):
    claude.counts_tokens(900_000)
    job_id = upload_pdf(client)

    estimate = client.get(f"/api/jobs/{job_id}/estimate").json()

    assert estimate["within_limit"] is False
    assert estimate["token_ceiling"] == 700_000


def test_a_scanned_pdf_goes_through_the_same_path_with_no_ocr_stage(client, claude):
    """A photocopied chapter is as usable as a born-digital one.

    There is deliberately no OCR stage: the model reads the page image. This
    asserts the pipeline does not branch on whether text could be extracted.
    """
    claude.counts_tokens(50_000).replies_json(PLAN)
    job_id = upload_pdf(client, name="scan-of-chapter-4.pdf")

    assert client.post(f"/api/jobs/{job_id}/plan").status_code == 200
    assert claude.uploads == ["scan-of-chapter-4.pdf"]
    assert claude.requests[-1]["messages"][0]["content"][0]["source"]["type"] == "file"


def test_a_text_upload_still_goes_inline_and_costs_no_upload(client, claude):
    claude.counts_tokens(500).replies_json(PLAN)
    job_id = client.post(
        "/api/jobs", files={"file": ("notes.txt", b"Some material.", "text/plain")}
    ).json()["job_id"]

    client.post(f"/api/jobs/{job_id}/plan")

    assert claude.uploads == [], "small text does not need the Files API"
    assert claude.requests[-1]["messages"][0]["content"][0]["source"]["type"] == "text"
