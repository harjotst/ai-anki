"""Importing an Anki deck: the file format in, our studiable deck out.

The one property everything else hangs on: an imported note keeps Anki's
own guid as its card_uuid, so exporting the deck later updates the notes
the person has been reviewing in Anki all along — import is not a fork.
"""

import genanki


def apkg_bytes(tmp_path, *, cloze=False, deck_name="Cardiology::Week 1"):
    deck = genanki.Deck(1746000001, deck_name)
    basic = genanki.Model(
        1746000002, "Basic",
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[{"name": "C1", "qfmt": "{{Front}}", "afmt": "{{Back}}"}],
    )
    deck.add_note(genanki.Note(model=basic, fields=[
        "What sets the <b>heart rate</b>?", "The SA node&nbsp;&mdash; the pacemaker.",
    ]))
    deck.add_note(genanki.Note(model=basic, fields=[
        "Normal ejection fraction?", "55–70%.<br>Below 40% is failure.",
    ]))
    if cloze:
        cloze_model = genanki.Model(
            1746000003, "Cloze", model_type=genanki.Model.CLOZE,
            fields=[{"name": "Text"}, {"name": "Extra"}],
            templates=[{"name": "C1", "qfmt": "{{cloze:Text}}", "afmt": "{{cloze:Text}}{{Extra}}"}],
        )
        deck.add_note(genanki.Note(model=cloze_model, fields=[
            "The AV node delays {{c1::conduction}}.", "",
        ]))
    path = tmp_path / "export.apkg"
    genanki.Package(deck).write_to_file(path)
    return path.read_bytes(), [note.guid for note in deck.notes]


def test_an_apkg_becomes_a_studiable_deck(client, tmp_path):
    content, guids = apkg_bytes(tmp_path, cloze=True)
    reply = client.post(
        "/api/decks/import",
        files={"file": ("cardio.apkg", content, "application/octet-stream")},
    )
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["cards"] == 3
    assert body["deck_name"] == "Cardiology"

    cards = client.get(f"/api/decks/{body['deck_id']}/cards").json()["cards"]
    assert {card["card_uuid"] for card in cards} == set(guids), (
        "identity is Anki's guid — the round trip depends on it"
    )
    by_front = {card["front"]: card for card in cards}
    asked = by_front["What sets the heart rate?"]
    assert asked["back"] == "The SA node — the pacemaker.", "HTML stripped, entities decoded"
    assert "Below 40% is failure." in by_front["Normal ejection fraction?"]["back"]
    cloze = next(card for card in cards if "{{c1::" in card["front"])
    assert cloze["note_type"] == "cloze"

    due = client.get(f"/api/decks/{body['deck_id']}/due").json()["cards"]
    assert len(due) == 3, "imported means studiable, immediately"


def test_a_file_that_is_not_an_export_says_so(client):
    refused = client.post(
        "/api/decks/import",
        files={"file": ("nope.apkg", b"not a zip at all", "application/octet-stream")},
    )
    assert refused.status_code == 422
    assert "zip" in refused.json()["detail"]
