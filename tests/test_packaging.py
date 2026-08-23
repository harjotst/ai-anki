import io
import zipfile

import genanki

from tests.test_generation import planned_job
from tests.test_planning import PLAN

CARDS_WITH_A_BROKEN_CLOZE = {
    "cards": [
        {
            "note_type": "cloze",
            "front": "Glycolysis occurs in the {{c1::cytosol}}.",
            "back": "",
        },
        {
            # Claude will occasionally emit a cloze card with no marker. genanki
            # 0.13.1 turns this into a note with ZERO cards, silently, and the
            # note still lands in the user's collection.
            "note_type": "cloze",
            "front": "Glycolysis has ten enzymatic steps.",
            "back": "",
        },
    ]
}

ONE_BASIC_CARD = {
    "cards": [{"note_type": "basic", "front": "Q?", "back": "A."}]
}


def generated_job(client, claude, first=CARDS_WITH_A_BROKEN_CLOZE, second=ONE_BASIC_CARD):
    job_id = planned_job(client, claude)
    claude.replies_json(first).replies_json(second)
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id


def test_downloading_a_generated_deck_returns_an_apkg(client, claude):
    job_id = generated_job(client, claude)

    response = client.get(f"/api/jobs/{job_id}/deck.apkg")

    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('.apkg"')

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert "collection.anki2" in archive.namelist()


def test_a_cloze_card_with_no_marker_is_downgraded_rather_than_silently_losing_its_cards(
    client, claude
):
    job_id = generated_job(client, claude)

    cards = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]

    assert cards[0]["note_type"] == "cloze"
    assert cards[1]["note_type"] == "basic", (
        "a cloze card with no {{cN::}} marker must be downgraded to basic; "
        "genanki would otherwise emit a note with zero cards and no warning"
    )


def test_the_note_type_model_ids_are_frozen_constants(client):
    # A model id that changes between exports makes Anki treat the note as
    # conflicting on re-import: it is neither updated nor added, and a junk
    # notetype is left behind in the user's collection.
    from app import packaging

    assert packaging.BASIC_MODEL.model_id == genanki.BASIC_MODEL.model_id
    assert packaging.CLOZE_MODEL.model_id == genanki.CLOZE_MODEL.model_id
    assert isinstance(packaging.BASIC_MODEL.model_id, int)


def test_deck_ids_are_stable_across_builds_for_the_same_path():
    from app import packaging

    assert packaging.deck_id_for("Biology::Metabolism") == packaging.deck_id_for(
        "Biology::Metabolism"
    )
    assert packaging.deck_id_for("Biology::Metabolism") != packaging.deck_id_for("Biology::Cells")


def test_math_markup_reaches_anki_in_its_own_delimiters():
    """We write $K_m$; Anki's MathJax reads \\(K_m\\). A raw dollar sign in
    an exported card is just a dollar sign, which is the bug this guards."""
    from app.packaging import anki_math

    assert anki_math("Rate is $V_{max}$ over $K_m$.") == r"Rate is \(V_{max}\) over \(K_m\)."
    # Dollar signs that are money, not markup: a span with no math structure
    # (_ ^ \) is left exactly as written.
    assert anki_math("costs $5, then $6 more") == "costs $5, then $6 more"
    # No markup, no change — and cloze markers survive untouched.
    assert anki_math("Vmax is {{c1::the ceiling}}") == "Vmax is {{c1::the ceiling}}"
