def test_uploading_a_text_file_creates_a_job(client):
    response = client.post(
        "/api/jobs",
        files={"file": ("lecture.txt", b"Glycolysis occurs in the cytosol.", "text/plain")},
    )

    assert response.status_code == 201
    job_id = response.json()["job_id"]
    assert job_id

    job = client.get(f"/api/jobs/{job_id}")

    assert job.status_code == 200
    assert job.json()["state"] == "uploaded"
    assert job.json()["source_filename"] == "lecture.txt"


def test_asking_for_a_job_that_does_not_exist_is_a_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_a_deck_is_named_for_humans_not_for_the_disk():
    """safe_filename's underscores are storage armour; a deck title made of
    them looked broken on every screen that showed it."""
    from app.jobs import deck_name_from

    assert deck_name_from("Introduction_to_the_Microbial_World_-_Honsa.pdf") == (
        "Introduction to the Microbial World - Honsa"
    )
    assert deck_name_from("week 3 renal.txt") == "week 3 renal"
    assert deck_name_from("...") == "New deck"
