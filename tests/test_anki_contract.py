"""Seam 2 — what only Anki can tell us.

These tests import our generated packages into a real Anki collection. They
exist because the identity constraints this project depends on are invisible
from the HTTP seam: a note that silently fails to update, a deck that never
moves, a cloze note with no cards. Each of those looks like success from our
side and only shows up in the user's collection.
"""

import ast
import tempfile
from pathlib import Path

import genanki

from app.jobs import Card
from app.packaging import build_package, deck_id_for
from tests.anki_harness import ANKI_VERSION, anki_collection


def basic(uuid: str, path: str, front: str = "Q?", back: str = "A.") -> Card:
    return Card(uuid, "topic", path, "basic", front, back)


def cloze(uuid: str, path: str, front: str, back: str = "") -> Card:
    return Card(uuid, "topic", path, "cloze", front, back)


# Two exports of the same deck, the second standing in for a regeneration a week
# later. The gap is load-bearing — see the timestamp test below.
EXPORTED_AT = 1_700_000_000.0
REGENERATED_AT = EXPORTED_AT + 604_800


def test_a_note_reimported_under_the_same_guid_updates_in_place_and_keeps_its_scheduling():
    """The claim the entire regeneration feature rests on."""
    first = build_package(
        [basic("g1", "Bio", "Old question", "Old answer")], "AI Anki", timestamp=EXPORTED_AT
    )
    revised = build_package(
        [basic("g1", "Bio", "New question", "New answer")], "AI Anki", timestamp=REGENERATED_AT
    )

    with anki_collection() as col:
        col.import_package(first)
        col.set_scheduling("g1", interval=90, reps=40)

        outcome = col.import_package(revised)

        assert outcome.updated == 1
        assert outcome.new == 0
        assert len(col.notes) == 1, "a matching GUID must update, never duplicate"
        assert col.note("g1").fields[0] == "New question"
        # Six weeks of review history survives the correction.
        assert col.scheduling("g1") == [(90, 40)]


def test_an_export_whose_timestamp_does_not_advance_silently_changes_nothing():
    """A trap, pinned here so nobody rediscovers it in a user's collection.

    Anki's default import setting compares modification times ("update if
    newer"). Two exports stamped at the same moment are not newer, so the second
    is filed as a duplicate and the note keeps its old content — reported as a
    successful import, with no error anywhere.
    """
    first = build_package([basic("g1", "Bio", "Old question")], "AI Anki", timestamp=EXPORTED_AT)
    same_instant = build_package(
        [basic("g1", "Bio", "New question")], "AI Anki", timestamp=EXPORTED_AT
    )

    with anki_collection() as col:
        col.import_package(first)
        outcome = col.import_package(same_instant)

        assert outcome.updated == 0
        assert outcome.duplicate == 1
        assert col.note("g1").fields[0] == "Old question", "the change was silently dropped"


def test_a_note_whose_guid_differs_is_added_alongside_rather_than_replacing():
    first = build_package([basic("g1", "Bio", "Question one")], "AI Anki")
    second = build_package([basic("g2", "Bio", "Question two")], "AI Anki")

    with anki_collection() as col:
        col.import_package(first)
        outcome = col.import_package(second)

        assert outcome.new == 1
        assert len(col.notes) == 2


def test_changing_a_notes_type_is_reported_as_conflicting_and_leaves_it_untouched():
    """Why note type is pinned per card for the life of the deck.

    Anki refuses to update a note whose notetype changed. It reports the note as
    conflicting and moves on — the old content stays, and nothing surfaces as an
    error. A plan editor that let a topic flip Basic to Cloze would produce an
    export that appears to succeed and does nothing.
    """
    first = build_package([basic("g1", "Bio", "Old question")], "AI Anki", timestamp=EXPORTED_AT)
    retyped = build_package(
        [cloze("g1", "Bio", "The answer is {{c1::phosphofructokinase}}.")],
        "AI Anki",
        timestamp=REGENERATED_AT,
    )

    with anki_collection() as col:
        col.import_package(first)
        outcome = col.import_package(retyped)

        assert outcome.conflicting == 1
        assert outcome.updated == 0
        assert col.note("g1").fields[0] == "Old question"


def test_a_cloze_note_produces_one_card_per_distinct_ordinal():
    package = build_package(
        [cloze("g1", "Bio", "{{c1::Glycolysis}} yields {{c2::2 ATP}} and {{c1::2 NADH}}.")],
        "AI Anki",
        timestamp=EXPORTED_AT,
    )

    with anki_collection() as col:
        col.import_package(package)

        # Two distinct ordinals across three markers.
        assert col.note("g1").card_count == 2


def test_a_marker_less_cloze_note_produces_zero_cards_which_is_why_we_downgrade():
    """The genanki defect our packaging guards against, demonstrated end to end.

    genanki 0.13.1's `_cloze_cards` compares a set against a dict
    (`if card_ords == {}`), which is never true, so a cloze note with no
    {{cN::}} marker yields no cards at all. The note still imports — it simply
    can never be reviewed. Built deliberately here, bypassing our own downgrade,
    to prove that guard is load-bearing rather than defensive.
    """
    deck = genanki.Deck(deck_id_for("Bypass"), "Bypass")
    deck.add_note(
        genanki.Note(model=genanki.CLOZE_MODEL, fields=["No marker anywhere.", ""], guid="g1")
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "raw.apkg"
        genanki.Package([deck]).write_to_file(str(path), timestamp=EXPORTED_AT)
        package = path.read_bytes()

    with anki_collection() as col:
        col.import_package(package)

        note = col.note("g1")
        assert note is not None, "the note lands in the collection"
        assert note.card_count == 0, "but with no cards, so it can never be reviewed"


def test_a_deck_path_produces_a_nested_hierarchy_with_parents_anki_creates_itself():
    package = build_package(
        [basic("g1", "Biology::Metabolism::Glycolysis")], deck_name="AI Anki"
    )

    with anki_collection() as col:
        col.import_package(package)

        assert "AI Anki::Biology::Metabolism::Glycolysis" in col.decks
        # We emit only the leaf deck; Anki materialises every parent.
        assert "AI Anki::Biology::Metabolism" in col.decks
        assert "AI Anki::Biology" in col.decks


def test_the_anki_version_under_test_is_pinned_and_recorded():
    # These assertions characterise one Anki version's behaviour. If the pin
    # moves, they must be re-run deliberately rather than drifting silently.
    assert ANKI_VERSION == "26.08.1"


def test_the_agpl_licensed_anki_package_is_never_imported_by_application_code():
    """`anki` is AGPL-3.0-or-later.

    Importing it from application code would impose the network-copyleft
    obligation on a publicly deployed service — every user could demand our
    source. It is a test dependency only. `genanki` (MIT) is what ships.
    """
    app_dir = Path(__file__).resolve().parent.parent / "app"
    offenders = []

    for path in sorted(app_dir.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == "anki" or name.startswith("anki."):
                    offenders.append(f"{path.name}:{node.lineno} imports {name}")

    assert offenders == [], f"AGPL package imported by application code: {offenders}"
