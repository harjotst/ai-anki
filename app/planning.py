"""Pass 1 — read the sources and propose a Deck Plan.

The plan is a flat array of topics, each carrying a `::` path string. It is
deliberately not a recursive tree: structured outputs reject recursive schemas,
so a self-referencing topic node would be a 400.
"""

from __future__ import annotations


MODEL = "claude-sonnet-5"

DIFFICULTIES = ["easy", "medium", "hard"]
NOTE_TYPES = ["basic", "cloze"]

# Numeric bounds (minimum/maximum/maxItems) are unsupported by structured
# outputs, so intent goes in the description and enforcement happens in Python
# after parsing.
DECK_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["topics"],
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "topic_id",
                    "path",
                    "difficulty",
                    "rationale",
                    "note_type",
                    "proposed_card_count",
                    "claims",
                ],
                "properties": {
                    "topic_id": {
                        "type": "string",
                        "description": "Short stable slug, unique within the plan.",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Anki deck path, '::' separated, e.g."
                            " 'Biology::Metabolism::Glycolysis'. Two or three levels."
                        ),
                    },
                    "difficulty": {"type": "string", "enum": DIFFICULTIES},
                    "rationale": {
                        "type": "string",
                        "description": "Why this difficulty, in one sentence.",
                    },
                    "note_type": {"type": "string", "enum": NOTE_TYPES},
                    "claims": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "The specific facts or points this topic alone covers. Every "
                            "claim must belong to exactly one topic: two topics covering "
                            "the same point produce the same card twice, in two decks."
                        ),
                    },
                    "proposed_card_count": {
                        "type": "integer",
                        "description": "Between 1 and 30. Scale with density, not length.",
                    },
                },
            },
        }
    },
}

# One system prompt, byte-identical across both passes. A pass-specific system
# prompt would change the prefix ahead of the documents and stop the generation
# pass from ever reading the cache written here.
SYSTEM = (
    "You build Anki decks from study material. You judge how much a body of "
    "material actually warrants: dense, interconnected content earns more cards "
    "and deeper question styles; thin or repetitive content earns fewer. You "
    "never pad to hit a number."
)

PLAN_INSTRUCTION = (
    "Read the material and propose a deck plan.\n\n"
    "Break it into topics that map onto Anki subdecks via '::' paths. For each "
    "topic, rate its difficulty, explain that rating in one sentence, choose "
    "whether its cards suit basic question/answer or cloze deletion, and propose "
    "a card count that reflects how much is genuinely worth remembering.\n\n"
    "Scale the whole plan to the material. A dense chapter may warrant many "
    "topics; a thin handout may warrant two.\n\n"
    "Partition the material: list the specific claims each topic owns, and give "
    "every claim to exactly one topic. Topics are written up separately and in "
    "parallel, so anything covered by two topics becomes the same card twice."
)


# How deep the user asked this deck to go, on a five-point scale. Level 3 —
# and an unset level — adds NOTHING: the model's own judgment of the material
# is the default, and these blocks exist to bend it deliberately in either
# direction, not to restate it. One vocabulary for all three passes, so the
# plan's granularity and the cards' depth move together.
DETAIL_LEVELS = {
    1: (
        "Depth 1 of 5 — essentials only. Keep only what the material treats as "
        "central; drop supporting detail, worked examples and edge cases. "
        "Propose few topics and small card counts."
    ),
    2: (
        "Depth 2 of 5 — light. Prefer the main mechanisms and their key facts; "
        "leave out most supporting detail. Keep card counts modest."
    ),
    3: "",
    4: (
        "Depth 4 of 5 — thorough. Include supporting details, exceptions and "
        "the relationships between mechanisms, not just the headlines. Card "
        "counts may run generous where the material carries them."
    ),
    5: (
        "Depth 5 of 5 — exhaustive. Everything the material commits to is fair "
        "game: numbers, exceptions, named regulators, edge cases. Propose as "
        "many cards as the material genuinely supports — but still never pad."
    ),
}


def detail_block(detail_level: int | None) -> str:
    text = DETAIL_LEVELS.get(detail_level or 3, "")
    return f"\n\n{text}" if text else ""


def guidance_block(guidance: str | None) -> str:
    """What the user themselves asked for, passed through to the planner.

    Their deck, their call: material they asked to focus on earns topics and
    cards; material they asked to skip gets none, however substantial it looks.
    """
    if not (guidance or "").strip():
        return ""
    return (
        "\n\nTHE USER'S OWN INSTRUCTIONS for this deck:\n"
        f"{guidance.strip()}\n\n"
        "Honour them when choosing topics and card counts: what they asked to "
        "focus on earns more; what they asked to skip gets nothing, however "
        "substantial it looks in the material."
    )


def text_document(text: str, filename: str) -> dict:
    return {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": text},
        "title": filename,
    }


def existing_topics_block(existing: list[dict]) -> str:
    """Tell pass 1 what the deck it is being added to already covers.

    Without this, week two invents its own identifiers for ground week one
    already holds. Pass 2 looks up existing cards by (deck, topic_id), so a
    renamed topic finds nothing to revise and every improved card arrives as a
    second note asking the same question — which the user then drills twice.

    Costs nothing to include: pass 1 is uncached, so a block that varies per
    deck breaks no prefix.
    """
    if not existing:
        return ""
    lines = "\n".join(
        f"- {topic['topic_id']} ({topic['path']}): {topic['card_count']} cards"
        for topic in existing
    )
    return (
        "\n\nEXISTING TOPICS in the deck this material is being added to:\n"
        f"{lines}\n\n"
        "Where this material covers ground one of these already holds, reuse "
        "that topic's topic_id and path VERBATIM. That is what lets an improved "
        "card update the note the user has been reviewing instead of arriving "
        "beside it. Invent a new topic_id only for genuinely new ground.\n"
    )


def build_plan_request(
    documents: list[dict],
    provider,
    existing_topics=None,
    guidance: str | None = None,
    detail_level: int | None = None,
) -> dict:
    """Assemble the pass-1 request.

    Deliberately NOT cached. Measured against the live API: a request carrying
    a different JSON schema gets its own cache lineage, and this is the only
    call in a job that sends DECK_PLAN_SCHEMA. An entry nothing ever reads still
    costs a write premium — 2x base input at a one-hour lifetime — so caching
    here is a pure loss.
    """
    return provider.build_request(
        system=SYSTEM,
        documents=documents,
        instruction=PLAN_INSTRUCTION
        + detail_block(detail_level)
        + guidance_block(guidance)
        + existing_topics_block(existing_topics or []),
        schema=DECK_PLAN_SCHEMA,
        max_tokens=16000,
        cache=None,
    )




# Structured outputs cannot express numeric bounds or array limits, so the model
# is asked in prose and the guarantee lives here. A plan the user edited comes
# through the same gate: the UI is not a trusted client.
MAX_CARDS_PER_TOPIC = 60
MAX_TOPICS = 60


class InvalidPlan(Exception):
    """A plan we will not generate from."""


def validate(plan: dict) -> dict:
    topics = (plan or {}).get("topics")
    if not isinstance(topics, list) or not topics:
        raise InvalidPlan("A plan needs at least one topic.")
    if len(topics) > MAX_TOPICS:
        raise InvalidPlan(f"A plan may have at most {MAX_TOPICS} topics.")

    seen = set()
    for topic in topics:
        path = str(topic.get("path", "")).strip()
        if not path:
            raise InvalidPlan("Every topic needs a deck path.")
        if path.startswith("::") or path.endswith("::") or "::::" in path:
            raise InvalidPlan(f"'{path}' is not a usable Anki deck path.")

        topic_id = str(topic.get("topic_id", "")).strip()
        if not topic_id:
            raise InvalidPlan("Every topic needs an identifier.")
        if topic_id in seen:
            raise InvalidPlan(f"Duplicate topic identifier '{topic_id}'.")
        seen.add(topic_id)

        count = topic.get("proposed_card_count")
        if not isinstance(count, int) or not 1 <= count <= MAX_CARDS_PER_TOPIC:
            raise InvalidPlan(
                f"Card count for '{path}' must be between 1 and {MAX_CARDS_PER_TOPIC}."
            )
        if str(topic.get("note_type", "")).lower() not in NOTE_TYPES:
            raise InvalidPlan(f"'{topic.get('note_type')}' is not a note type.")
        if str(topic.get("difficulty", "")).lower() not in DIFFICULTIES:
            raise InvalidPlan(f"'{topic.get('difficulty')}' is not a difficulty.")
    return plan


def render_cloze(front: str) -> str:
    """What a cloze card looks like when it is asked.

    Judging a cloze card from its markup is judging the wrong thing.
    """
    import re

    return re.sub(r"\{\{c\d+::(.*?)(?:::([^}]*))?\}\}", lambda m: m.group(2) or "[...]", front or "")
