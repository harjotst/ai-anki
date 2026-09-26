"""What the user tells us at upload: the deck's name, and their own brief.

A new deck's name is required — there is no default made from the filename.
The rest is voluntary: the real filename (the phone's document picker uploads
a cache copy whose basename is a UUID), and a brief: free-text focus/skip
instructions plus a five-point depth scale. These tests pin where each lands:
the name on the deck, the filename on the source, the brief in every pass's
prompt, and — just as deliberately — NOTHING in the prompt when the user said
nothing, so the default deck is exactly the deck this app always built.
"""

import pytest

from tests.test_generation import CELL_CARDS, GLYCOLYSIS_CARDS
from tests.test_planning import PLAN


def post(client, *, name="lecture.txt", **fields):
    data = {k: v for k, v in fields.items() if v is not None}
    return client.post(
        "/api/jobs",
        files={"file": (name, b"Glycolysis occurs in the cytosol.", "text/plain")},
        data=data,
    )


def upload(client, *, name="lecture.txt", deck_name="Metabolism", **fields):
    return post(client, name=name, deck_name=deck_name, **fields).json()["job_id"]


def instruction_of(request: dict) -> str:
    return request["messages"][0]["content"][-1]["text"]


# --- names ----------------------------------------------------------------


def test_the_source_keeps_the_filename_the_user_actually_picked(client):
    """The picker's cache copy arrives named by UUID; the form field wins."""
    job_id = upload(
        client,
        name="28E16C71-E238-4ECE-A764-712C65E21C74.pdf",
        filename="Integration of Metabolism.pdf",
    )
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["source_filename"] == "Integration of Metabolism.pdf"


def test_the_deck_is_called_what_the_user_named_it(client):
    job_id = upload(client, filename="week3.pdf", deck_name="  Midterm 2   cram ")
    job = client.get(f"/api/jobs/{job_id}").json()
    decks = client.get("/api/decks").json()["decks"]
    assert next(d for d in decks if d["deck_id"] == job["deck_id"])["name"] == "Midterm 2 cram"


@pytest.mark.parametrize("deck_name", [None, "", "   "])
def test_a_new_deck_without_a_name_is_refused(client, deck_name):
    """No filename fallback: a deck named `week-3-final-FINAL` is a deck nobody
    can find six weeks later. Refused before anything is stored."""
    reply = post(client, filename="week3.pdf", deck_name=deck_name)

    assert reply.status_code == 422
    assert reply.json()["detail"] == "a deck needs a name"
    assert client.get("/api/jobs").json()["jobs"] == []
    assert client.get("/api/decks").json()["decks"] == []


def test_a_new_deck_name_follows_the_rename_rules(client):
    reply = post(client, deck_name="Bio::Week 3")
    assert reply.status_code == 422


def test_adding_to_an_existing_deck_needs_no_name(client):
    first = client.get(f"/api/jobs/{upload(client)}").json()
    reply = post(client, deck_id=first["deck_id"])
    assert reply.status_code == 201, reply.text


# --- the brief ------------------------------------------------------------


def test_guidance_reaches_the_planner_verbatim(client, claude):
    claude.replies_json(PLAN)
    job_id = upload(client, guidance="Focus on hormones; skip the history section.")
    client.post(f"/api/jobs/{job_id}/plan")
    instruction = instruction_of(claude.requests[-1])
    assert "Focus on hormones; skip the history section." in instruction
    assert "THE USER'S OWN INSTRUCTIONS" in instruction


def test_detail_level_bends_all_three_passes(client, claude):
    claude.replies_json(PLAN)
    job_id = upload(client, detail_level="5")
    client.post(f"/api/jobs/{job_id}/plan")
    assert "Depth 5 of 5" in instruction_of(claude.requests[-1])

    claude.replies_json(GLYCOLYSIS_CARDS).replies_json(CELL_CARDS)
    client.post(f"/api/jobs/{job_id}/generate")
    for kind in ("lesson", "cards"):
        for request in claude.calls_for(kind):
            assert "Depth 5 of 5" in instruction_of(request), kind


def test_saying_nothing_adds_nothing_to_any_prompt(client, claude):
    """Level 3 and silence are the same deck: the model's own judgment."""
    claude.replies_json(PLAN)
    job_id = upload(client, detail_level="3")
    client.post(f"/api/jobs/{job_id}/plan")
    instruction = instruction_of(claude.requests[-1])
    assert "Depth" not in instruction
    assert "THE USER'S OWN INSTRUCTIONS" not in instruction


def test_a_detail_level_off_the_scale_is_refused(client):
    reply = client.post(
        "/api/jobs",
        files={"file": ("a.txt", b"Some material.", "text/plain")},
        data={"detail_level": "6"},
    )
    assert reply.status_code == 422


def test_the_brief_reads_back_on_the_job(client):
    job_id = upload(client, guidance="hormones only", detail_level="4")
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["guidance"] == "hormones only"
    assert job["detail_level"] == 4
