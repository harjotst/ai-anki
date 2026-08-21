"""Test-only harness around a real Anki collection.

The official `anki` package is AGPL-3.0-or-later. Importing it from application
code would impose the network-copyleft obligation on a publicly deployed
service, so it lives here and only here — `test_the_agpl_licensed_anki_package_
is_never_imported_by_application_code` enforces that boundary.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from anki.buildinfo import version as ANKI_VERSION
from anki.collection import Collection, ImportAnkiPackageOptions, ImportAnkiPackageRequest


@dataclass(frozen=True)
class ImportedNote:
    guid: str
    notetype: str
    fields: list[str]
    card_count: int
    deck_names: list[str]
    tags: list[str]


@dataclass(frozen=True)
class ImportOutcome:
    """The counts Anki reports back, which is where silent failures surface."""

    new: int
    updated: int
    conflicting: int
    duplicate: int


class AnkiCollection:
    def __init__(self, directory: Path):
        self._dir = directory
        self._col = Collection(str(directory / "collection.anki2"))
        self._counter = 0

    def import_package(self, package: bytes, **options) -> ImportOutcome:
        """Import a package. Options default to Anki's own import-screen defaults."""
        self._counter += 1
        path = self._dir / f"import-{self._counter}.apkg"
        path.write_bytes(package)
        response = self._col.import_anki_package(
            ImportAnkiPackageRequest(
                package_path=str(path),
                options=ImportAnkiPackageOptions(**options),
            )
        )
        log = response.log
        return ImportOutcome(
            new=len(log.new),
            updated=len(log.updated),
            conflicting=len(log.conflicting),
            duplicate=len(log.duplicate),
        )

    @property
    def decks(self) -> set[str]:
        return {entry.name for entry in self._col.decks.all_names_and_ids()}

    @property
    def notes(self) -> list[ImportedNote]:
        found = []
        for note_id in self._col.find_notes(""):
            note = self._col.get_note(note_id)
            card_ids = note.card_ids()
            found.append(
                ImportedNote(
                    guid=note.guid,
                    notetype=note.note_type()["name"],
                    fields=list(note.fields),
                    card_count=len(card_ids),
                    deck_names=[
                        self._col.decks.name(self._col.get_card(cid).did) for cid in card_ids
                    ],
                    tags=list(note.tags),
                )
            )
        return found

    def note(self, guid: str) -> ImportedNote | None:
        return next((n for n in self.notes if n.guid == guid), None)

    def set_scheduling(self, guid: str, *, interval: int, reps: int) -> None:
        """Give a note's cards a review history, so an update can be shown to preserve it."""
        note = next(n for n in self._col.find_notes("") if self._col.get_note(n).guid == guid)
        for card_id in self._col.get_note(note).card_ids():
            card = self._col.get_card(card_id)
            card.ivl = interval
            card.reps = reps
            card.type = 2  # review
            card.queue = 2
            self._col.update_card(card)

    def scheduling(self, guid: str) -> list[tuple[int, int]]:
        note_id = next(n for n in self._col.find_notes("") if self._col.get_note(n).guid == guid)
        return [
            (self._col.get_card(cid).ivl, self._col.get_card(cid).reps)
            for cid in self._col.get_note(note_id).card_ids()
        ]

    def close(self) -> None:
        self._col.close()


@contextmanager
def anki_collection():
    with tempfile.TemporaryDirectory() as directory:
        collection = AnkiCollection(Path(directory))
        try:
            yield collection
        finally:
            collection.close()
