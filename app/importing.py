"""Importing somebody's existing Anki deck.

An .apkg is a zip holding a SQLite database. The legacy database
(`collection.anki21` / `collection.anki2`, schema 11) is what every Anki
export includes unless "support older versions" was unchecked — the newer
`collection.anki21b` is zstd-compressed and deliberately not parsed here;
the person is told to re-export rather than us shipping half a decoder.

The imported card keeps Anki's own note guid as its `card_uuid`. That is
the whole trick: our exports hand `card_uuid` to genanki as the guid, so a
deck that came from Anki and later goes back to Anki updates the notes the
person has been reviewing all along instead of duplicating them.

No lessons are created — nothing taught these cards — and media is not
carried over (a v1 boundary, stated rather than hidden).
"""

from __future__ import annotations

import html
import io
import json
import re
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path

import psycopg

from app import db, study


class NotAnApkg(Exception):
    """The file could not be read as an Anki export."""


FIELD_SEP = "\x1f"
_SOUND = re.compile(r"\[sound:[^\]]*\]")
_IMG = re.compile(r"<img[^>]*>", re.I)
_BREAKS = re.compile(r"<(?:br|/div|/p|/li)\s*/?>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n{3,}")


def readable_field(raw: str) -> str:
    """Anki fields are HTML; ours are text. Keep the words, drop the markup."""
    text = _SOUND.sub("", raw)
    text = _IMG.sub("", text)
    text = _BREAKS.sub("\n", text)
    text = _TAGS.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    return _BLANK_LINES.sub("\n\n", text).strip()


def _collection(archive: zipfile.ZipFile) -> bytes:
    for name in ("collection.anki21", "collection.anki2"):
        if name in archive.namelist():
            return archive.read(name)
    if "collection.anki21b" in archive.namelist():
        raise NotAnApkg(
            "this export uses Anki's newest format — re-export it with "
            "\"Support older Anki versions\" checked and it will import"
        )
    raise NotAnApkg("no Anki collection inside this file")


def import_apkg(
    conn: psycopg.Connection, account_id: str, content: bytes, filename: str
) -> dict:
    """One .apkg becomes one deck, its notes become cards, studiable now."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise NotAnApkg("not an .apkg — the file is not a zip archive") from exc

    raw = _collection(archive)
    with tempfile.NamedTemporaryFile(suffix=".anki2") as handle:
        handle.write(raw)
        handle.flush()
        source = sqlite3.connect(f"file:{handle.name}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        try:
            col = source.execute("SELECT models, decks FROM col").fetchone()
            models = {int(k): v for k, v in json.loads(col["models"]).items()}
            anki_decks = {int(k): v for k, v in json.loads(col["decks"]).items()}
            notes = source.execute("SELECT id, guid, mid, flds FROM notes").fetchall()
            deck_of_note = {
                row["nid"]: row["did"]
                for row in source.execute(
                    "SELECT nid, MIN(did) AS did FROM cards GROUP BY nid"
                )
            }
        finally:
            source.close()

    if not notes:
        raise NotAnApkg("this export contains no notes")

    deck_name = Path(filename).stem.replace("_", " ").strip() or "Imported deck"
    top = [d["name"] for d in anki_decks.values() if d.get("name") and d["name"] != "Default"]
    if len({name.split("::")[0] for name in top}) == 1:
        deck_name = top[0].split("::")[0]

    deck_id = uuid.uuid4().hex
    job_id = uuid.uuid4().hex
    now = db.now()
    conn.execute(
        "INSERT INTO deck (id, account_id, name, created_at) VALUES (%s,%s,%s,%s)",
        (deck_id, account_id, deck_name, now),
    )
    conn.execute(
        "INSERT INTO job (deck_id, id, account_id, state, created_at)"
        " VALUES (%s,%s,%s,'complete',%s)",
        (deck_id, job_id, account_id, now),
    )
    conn.execute(
        "INSERT INTO topic (job_id, topic_id, position, status, topic_json)"
        " VALUES (%s,'imported',0,'complete',%s)",
        (job_id, json.dumps({"topic_id": "imported", "path": deck_name})),
    )

    count = 0
    for position, note in enumerate(notes):
        model = models.get(note["mid"], {})
        fields = [readable_field(part) for part in note["flds"].split(FIELD_SEP)]
        front = fields[0] if fields else ""
        back = "\n\n".join(part for part in fields[1:] if part)
        if not front:
            continue
        note_type = "cloze" if model.get("type") == 1 else "basic"
        anki_deck = anki_decks.get(deck_of_note.get(note["id"], -1), {})
        deck_path = anki_deck.get("name") or deck_name
        conn.execute(
            "INSERT INTO card (job_id, card_uuid, topic_id, deck_path, note_type,"
            "                  front, back, difficulty, deck_id,"
            "                  question_fingerprint, position)"
            " VALUES (%s,%s,'imported',%s,%s,%s,%s,'medium',%s,%s,%s)"
            " ON CONFLICT DO NOTHING",
            (job_id, note["guid"], deck_path, note_type, front, back,
             deck_id, front.lower()[:80], position),
        )
        count += 1

    if not count:
        raise NotAnApkg("every note in this export was empty")

    study.enrol(conn, account_id, deck_id)
    return {"deck_id": deck_id, "deck_name": deck_name, "cards": count}
