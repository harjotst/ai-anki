"""Pass 2 — generate the cards for one topic.

Each topic gets its own request. The prefix (system prompt, then the documents)
is byte-identical to pass 1's, so pass 1 writes the cache and every topic call
reads it. The topic-specific instruction goes after the documents, never in the
system prompt — a differing system tier would make the document tier unmatched
and every call would pay full price.
"""

from __future__ import annotations

from app.planning import NOTE_TYPES, SYSTEM, detail_block

CARDS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cards"],
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["note_type", "front", "back", "source_page", "existing_card_id"],
                "properties": {
                    "note_type": {"type": "string", "enum": NOTE_TYPES},
                    "front": {
                        "type": "string",
                        "description": (
                            "For a basic card, the question. For a cloze card, the full "
                            "sentence with at least one {{c1::...}} deletion marker."
                        ),
                    },
                    "back": {
                        "type": "string",
                        "description": (
                            "For a basic card, the answer. For a cloze card, any extra "
                            "context to show after the answer; may be empty."
                        ),
                    },
                    "existing_card_id": {
                        "type": ["string", "null"],
                        "description": (
                            "The id of the existing card this one revises, taken verbatim "
                            "from the EXISTING CARDS list. Null for a genuinely new card. "
                            "Never guess: an id is only correct if the card asks "
                            "substantially the same question."
                        ),
                    },
                    "source_page": {
                        "type": ["integer", "null"],
                        "description": (
                            "1-based page of the source this card came from, or null if "
                            "the material has no pages. Self-reported."
                        ),
                    },
                },
            },
        }
    },
}

_STYLE = {
    "easy": "Ask direct recall questions.",
    "medium": "Mix recall with questions that require relating two facts.",
    "hard": (
        "Favour application, comparison, and cause-and-effect over definitions. "
        "A card should test whether the material is understood, not merely seen. "
        "Make the QUESTION harder, never the answer longer."
    ),
}

# Stated for every difficulty rather than only the easy one, because a harder
# question is exactly what makes this rule easy to break. Measured on a real
# 164-card run: 9% of answers packed three or more facts, all of them in hard
# topics. A card whose answer is a list is never quite right and never quite
# wrong, so it is graded 'again' for weeks and drags the schedule around it
# down with it.
_ATOMICITY = (
    "\n\nEvery card tests ONE fact, and its answer is one fact long — a term, a "
    "value, a mechanism, a single sentence. If an answer would need "
    "\"and\", a comma-separated list, or more than about fifteen words, split it "
    "into that many cards instead. Two sharp cards beat one card carrying "
    "three facts, and count towards the target the same way.\n"
)


def existing_cards_block(existing: list[dict]) -> str:
    """Tell the model what this topic already has, so it can declare revisions."""
    if not existing:
        return (
            "\n\nEXISTING CARDS: none. This topic has never been exported, so every "
            "card is new and existing_card_id must be null.\n"
        )
    lines = "\n".join(
        f"- {card['card_uuid']}: {card['last_exported_front']}" for card in existing
    )
    return (
        "\n\nEXISTING CARDS already in the user's collection for this topic:\n"
        f"{lines}\n\n"
        "If a card you write revises one of these, set existing_card_id to its id so "
        "the user's review history is kept. If it asks a different question, set "
        "existing_card_id to null. A wrong id attaches someone's review history to a "
        "question they have never seen, so leave it null when unsure.\n"
    )


def siblings_block(siblings: list[dict]) -> str:
    """Name what other topics own, so this one does not write it too."""
    if not siblings:
        return ""
    lines = "\n".join(
        f"- {s['path']}: " + "; ".join(s.get("claims") or []) for s in siblings
    )
    return (
        "\n\nOTHER TOPICS own the following and are being written separately. Do "
        f"NOT write cards for any of it:\n{lines}\n"
    )


def build_cards_request(
    documents: list[dict],
    topic: dict,
    provider,
    existing: list[dict] | None = None,
    siblings: list[dict] | None = None,
    detail_level: int | None = None,
) -> dict:
    difficulty = str(topic.get("difficulty", "medium")).lower()
    instruction = (
        f"Generate cards for one topic only: {topic['path']}\n\n"
        f"Difficulty: {difficulty}. {_STYLE.get(difficulty, _STYLE['medium'])}\n"
        f"{_ATOMICITY}"
        f"Target roughly {topic['proposed_card_count']} cards, and prefer "
        f"{topic['note_type']} note type where it fits the content.\n\n"
        "Cover only this topic. Do not generate cards for material that belongs "
        "to a different topic in the deck.\n\n"
        "Every cloze card's front must contain at least one {{c1::...}} marker.\n\n"
        "Scientific notation is notation: write it as inline math markup — "
        "$V_{max}$, $k_{cat}$, $K_m$, $Ca^{2+}$, $t_{1/2}$ — dollar-delimited "
        "with LaTeX-style _{} and ^{} and nothing more. Plain-text spellings "
        "such as Vmax or Ca2+ are wrong."
        + (
            "\n\nThis topic owns these points and only these:\n"
            + "\n".join(f"- {claim}" for claim in topic.get("claims") or [])
            if topic.get("claims")
            else ""
        )
        + detail_block(detail_level)
        + siblings_block(siblings or [])
        + existing_cards_block(existing or [])
    )
    # Five minutes, not an hour. Every topic call sends this same schema, so
    # they DO share a prefix — the first writes it and the rest read it. They
    # run back-to-back in the worker with no human pause between them, and an
    # hour costs 2x base input against 1.25x for five minutes.
    #
    # They do NOT share with the planning pass. Measured against the live API on
    # 2026-08-17: a request carrying a different JSON schema gets its own cache
    # lineage, because structured outputs render ahead of the messages.
    return provider.build_request(
        system=SYSTEM,
        documents=documents,
        instruction=instruction,
        schema=CARDS_SCHEMA,
        max_tokens=16000,
        cache="5m",
    )
