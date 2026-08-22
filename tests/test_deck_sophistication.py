"""What makes a complicated document produce a complicated deck.

Hierarchy, mixed note types and tags are the levers. Every claim here is checked
against a real Anki collection rather than against our own code, because the
failure modes are silent from our side.
"""

from app.jobs import Card
from app.packaging import BASIC_MODEL, CLOZE_MODEL, build_package
from tests.anki_harness import anki_collection

PLAN = {
    "topics": [
        {
            "topic_id": "glycolysis",
            "path": "Biology::Metabolism::Glycolysis",
            "difficulty": "hard",
            "rationale": "Dense pathway.",
            "note_type": "cloze",
            "proposed_card_count": 2,
        }
    ]
}

CARDS = {
    "cards": [
        {
            "note_type": "cloze",
            "front": "Glycolysis occurs in the {{c1::cytosol}} yielding {{c2::2 ATP}}.",
            "back": "",
            "source_page": 4,
        },
        {
            "note_type": "basic",
            "front": "Which enzyme is rate-limiting?",
            "back": "PFK-1.",
            "source_page": 5,
        },
    ]
}


def upload(client, text=b"Glycolysis material."):
    return client.post(
        "/api/jobs", files={"file": ("lecture.txt", text, "text/plain")}
    ).json()["job_id"]


def generated(client, claude, cards=CARDS):
    claude.replies_json(PLAN)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    claude.replies_json(cards)
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id


def test_cards_carry_topic_difficulty_source_page_and_job_tags(client, claude):
    job_id = generated(client, claude)

    cards = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]

    tags = cards[0]["tags"]
    assert "topic::glycolysis" in tags
    assert "difficulty::hard" in tags
    assert "page::4" in tags
    # One search string finds the whole batch, which is how a bad import is undone.
    assert f"aianki::job::{job_id}" in tags
    assert all(" " not in tag for tag in tags), "Anki splits tags on whitespace"


def test_a_real_collection_shows_the_hierarchy_note_types_cloze_cards_and_tags(client, claude):
    job_id = generated(client, claude)
    package = client.get(f"/api/jobs/{job_id}/deck.apkg").content

    with anki_collection() as col:
        col.import_package(package)

        assert "AI Anki::Biology::Metabolism::Glycolysis" in col.decks
        assert "AI Anki::Biology::Metabolism" in col.decks

        by_type = {note.notetype: note for note in col.notes}
        assert set(by_type) == {"Cloze (genanki)", "Basic (genanki)"}
        # Two deletions, so Anki generates two cards from the one note.
        assert by_type["Cloze (genanki)"].card_count == 2
        assert by_type["Basic (genanki)"].card_count == 1

        assert f"aianki::job::{job_id}" in by_type["Basic (genanki)"].tags
        assert "difficulty::hard" in by_type["Basic (genanki)"].tags


def test_a_cloze_card_without_a_marker_is_downgraded_and_the_downgrade_is_recorded(
    client, claude
):
    broken = {
        "cards": [
            {
                "note_type": "cloze",
                "front": "Glycolysis has ten enzymatic steps.",
                "back": "",
                "source_page": 1,
            }
        ]
    }
    job_id = generated(client, claude, cards=broken)

    card = client.get(f"/api/jobs/{job_id}/cards").json()["cards"][0]

    assert card["note_type"] == "basic"
    # Recorded, not merely corrected: a topic quietly producing unusable cloze
    # text is a prompt problem, and silently fixing it hides that.
    assert card["downgraded"] is True

    with anki_collection() as col:
        col.import_package(client.get(f"/api/jobs/{job_id}/deck.apkg").content)
        assert col.notes[0].card_count == 1, "the note must not arrive with zero cards"


def test_the_note_type_definitions_are_frozen():
    """A changed field or template list is a schema migration, not an edit.

    Anki keys a notetype by id. Changing what that id means while keeping the id
    leaves every existing note pointing at a definition it no longer matches.
    """
    assert BASIC_MODEL.model_id == 1559383000
    assert [field["name"] for field in BASIC_MODEL.fields] == ["Front", "Back"]
    assert [template["name"] for template in BASIC_MODEL.templates] == ["Card 1"]

    assert CLOZE_MODEL.model_id == 1550428389
    assert [field["name"] for field in CLOZE_MODEL.fields] == ["Text", "Back Extra"]
    assert [template["name"] for template in CLOZE_MODEL.templates] == ["Cloze"]


def test_difficulty_shapes_the_question_style_not_only_the_card_count(client, claude):
    claude.replies_json(PLAN)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    claude.replies_json(CARDS)
    client.post(f"/api/jobs/{job_id}/generate")

    instruction = claude.requests[-1]["messages"][0]["content"][-1]["text"].lower()

    assert "hard" in instruction
    # A hard topic must ask for more than definitions, or "difficulty" only ever
    # means "how many".
    assert "application" in instruction or "comparison" in instruction


def test_only_leaf_decks_are_emitted_and_anki_fills_in_the_parents():
    package = build_package(
        [Card("g1", "t", "Biology::Metabolism::Glycolysis", "basic", "Q", "A")],
        deck_name="AI Anki",
        timestamp=1.0,
    )

    with anki_collection() as col:
        col.import_package(package)
        assert "AI Anki::Biology::Metabolism::Glycolysis" in col.decks
        assert "AI Anki::Biology" in col.decks


def test_a_hard_card_is_still_one_question_with_one_answer(client, claude):
    """Measured on a real run: 9% of answers packed three or more facts.

    "Hard" was being read as "put more in it". A card whose answer is a list is
    a card that is never quite right and never quite wrong, so it is graded
    'again' for weeks and the schedule for everything around it degrades with
    it. Difficulty has to mean a harder question, not a longer answer.
    """
    claude.replies_json(PLAN)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    claude.replies_json(CARDS)
    client.post(f"/api/jobs/{job_id}/generate")

    instruction = claude.requests[-1]["messages"][0]["content"][-1]["text"].lower()

    # The constraint is stated for every difficulty, because it is the one rule
    # that a harder question makes it easier to break.
    assert "one fact" in instruction or "single fact" in instruction
    assert "split" in instruction
