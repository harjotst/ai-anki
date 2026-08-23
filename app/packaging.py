"""Build the .apkg.

Two constraints here were established by importing generated packages into a
real Anki collection, not by reading genanki:

1. Model ids must be frozen. Anki's importer skips a note whose notetype_id
   differs from the existing one — logged as conflicting, not updated — so a
   per-job random id (as genanki's README suggests) silently breaks re-import.
2. A cloze note whose text carries no {{cN::}} marker produces zero cards.
   genanki 0.13.1 has `if card_ords == {}`, comparing a set against a dict, which
   is always False. Fixed upstream, never released. We validate before building.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

import genanki

# genanki's built-in models carry fixed ids and are deliberately named
# "Basic (genanki)" / "Cloze (genanki)" so they don't collide with Anki's own.
BASIC_MODEL = genanki.BASIC_MODEL
CLOZE_MODEL = genanki.CLOZE_MODEL

CLOZE_MARKER = re.compile(r"\{\{c\d+::")


def has_cloze_marker(text: str) -> bool:
    return CLOZE_MARKER.search(text) is not None


def anki_math(text: str) -> str:
    r"""Our inline $...$ markup, in the delimiters Anki's MathJax reads.

    Anki renders \( ... \) natively; a raw dollar sign is just a dollar
    sign there. Converted at this boundary only — the app's own renderer
    reads the $ form, and the ledger stores what the model wrote.
    """
    # Only spans that contain math structure. "costs $5, then $6 more" has
    # two dollar signs and no formula, and must come out untouched.
    return re.sub(
        r"\$([^$]*[_^\\][^$]*)\$", lambda m: r"\(" + m.group(1) + r"\)", text
    )


def effective_note_type(note_type: str, front: str) -> str:
    """Downgrade a cloze card that would produce no cards at all."""
    if note_type == "cloze" and not has_cloze_marker(front):
        return "basic"
    return note_type


def deck_id_for(deck_path: str) -> int:
    """A stable id per deck path.

    Anki matches decks by name on import, so the id barely matters for
    placement — but it must be stable and valid, and deriving it from the path
    keeps rebuilds deterministic.
    """
    digest = hashlib.sha256(deck_path.encode()).digest()
    return int.from_bytes(digest[:4], "big") | (1 << 30)


def build_package(cards, deck_name: str, timestamp: float | None = None) -> bytes:
    """Build an .apkg.

    `timestamp` becomes every note's modification time. It matters more than it
    looks: Anki's default import setting is "update notes if newer", comparing
    that mod time against the note already in the collection. An export whose
    timestamp does not advance past the previous one is filed as a duplicate and
    changes nothing — silently. Regeneration must therefore always stamp a
    strictly later time than the export it supersedes.
    """
    decks: dict[str, genanki.Deck] = {}

    for card in cards:
        # Only leaf decks are emitted — Anki creates the intermediate parents.
        path = f"{deck_name}::{card.deck_path}"
        deck = decks.get(path)
        if deck is None:
            deck = decks[path] = genanki.Deck(deck_id_for(path), path)

        front, back = anki_math(card.front), anki_math(card.back)
        if effective_note_type(card.note_type, card.front) == "cloze":
            model, fields = CLOZE_MODEL, [front, back]
        else:
            model, fields = BASIC_MODEL, [front, back]

        # The stable uuid becomes the note GUID. Without it genanki hashes the
        # field content, so any edit would look like a brand-new note.
        deck.add_note(
            genanki.Note(
                model=model, fields=fields, guid=card.card_uuid, tags=list(card.tags)
            )
        )

    package = genanki.Package(list(decks.values()))
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "deck.apkg"
        package.write_to_file(str(out), timestamp=timestamp)
        return out.read_bytes()
