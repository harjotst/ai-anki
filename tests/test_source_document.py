"""The document a deck was made from, handed back to the person who made it.

A deck's history used to list filenames that led nowhere. A name you cannot
open is not worth a screen, so the phone now opens the upload itself — and
this is the door it comes through.
"""

from tests.conftest import SOMEBODY_ELSE

PDF = b"%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


def upload(client, name="Glycolysis.pdf", content=PDF, kind="application/pdf"):
    response = client.post(
        "/api/jobs",
        files={"file": ("cache-copy", content, kind)},
        data={"deck_name": "Metabolism", "filename": name},
    )
    assert response.status_code == 201
    return response.json()["job_id"]


def test_the_owner_gets_their_upload_back_byte_for_byte(client):
    job_id = upload(client)

    response = client.get(f"/api/jobs/{job_id}/source")

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    # The name the person picked, not the picker's cache basename.
    assert "Glycolysis.pdf" in response.headers["content-disposition"]


def test_a_text_upload_comes_back_as_text(client):
    job_id = upload(client, name="notes.txt", content=b"Some material.", kind="text/plain")

    response = client.get(f"/api/jobs/{job_id}/source")

    assert response.status_code == 200
    assert response.content == b"Some material."
    assert response.headers["content-type"].startswith("text/plain")


def test_somebody_elses_upload_is_missing_rather_than_forbidden(client):
    job_id = upload(client)

    client.sign_in_as(SOMEBODY_ELSE)

    assert client.get(f"/api/jobs/{job_id}/source").status_code == 404


def test_a_purged_upload_says_it_is_gone_rather_than_missing(client):
    """The job is real and is theirs; only the file went. The phone says so
    in words instead of showing a broken reader."""
    job_id = upload(client)
    assert client.post("/api/maintenance/purge", json={"older_than_days": 0}).status_code == 200

    response = client.get(f"/api/jobs/{job_id}/source")

    assert response.status_code == 410
    assert response.json()["detail"] == "the original file is no longer stored"
