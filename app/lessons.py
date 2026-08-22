"""Pass 2a — teach one topic.

Cards reinforce comprehension; they do not create it. Somebody handed 164 cards
on material they have not understood drills wrong models into long-term memory,
and the scheduler faithfully keeps them there. So the lesson is written first,
and it is the thing the user actually reads.

Pass 1 already produced the syllabus this reads from: topics in dependency
order, each carrying a difficulty, a written reason for it, and the exclusive
list of Claims it owns. Everything except the card counts used to be discarded.

The prefix -- system prompt, then the documents -- is byte-identical to the
other passes', but that does not mean they share a cache. Measured against the
live API on 2026-08-17: a request carrying a different JSON schema gets its own
cache lineage, because structured outputs render ahead of the messages. Lessons
share with lessons, cards share with cards, and neither can read the other's --
which is why each needs its own pacesetter call before the rest fan out.
"""

from __future__ import annotations

from app.planning import SYSTEM

LESSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "in_one_line",
        "why_it_matters",
        "sections",
        "worked_example",
        "misconceptions",
        "check_yourself",
    ],
    "properties": {
        "in_one_line": {
            "type": "string",
            "description": "What this topic is, in one sentence a beginner could repeat.",
        },
        "why_it_matters": {
            "type": "string",
            "description": (
                "Why somebody studying this course needs it — what it explains or "
                "makes possible. Not a restatement of the definition."
            ),
        },
        "sections": {
            "type": "array",
            "description": (
                "The concepts, in the order they have to be learned. Each one may "
                "assume only what came before it."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["heading", "body", "builds_on"],
                "properties": {
                    "heading": {"type": "string"},
                    "body": {
                        "type": "string",
                        "description": (
                            "Two to four short paragraphs. Explain the mechanism, not "
                            "only the name of it."
                        ),
                    },
                    "builds_on": {
                        "type": ["string", "null"],
                        "description": (
                            "The heading of the earlier section this one depends on, "
                            "verbatim, or null if it stands alone."
                        ),
                    },
                },
            },
        },
        "worked_example": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["problem", "walkthrough"],
            "description": (
                "One problem worked through end to end. Null when the material is "
                "descriptive and there is genuinely nothing to work."
            ),
            "properties": {
                "problem": {"type": "string"},
                "walkthrough": {
                    "type": "string",
                    "description": "Each step, and why that step follows from the last.",
                },
            },
        },
        "misconceptions": {
            "type": "array",
            "description": (
                "What people actually get wrong here. This is the part a textbook "
                "does badly and the part worth the most: a belief named and "
                "corrected is a card that will not be failed for six weeks."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["belief", "why_it_is_wrong"],
                "properties": {
                    "belief": {
                        "type": "string",
                        "description": "The wrong idea, stated the way somebody holding it would.",
                    },
                    "why_it_is_wrong": {"type": "string"},
                },
            },
        },
        "check_yourself": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Questions to answer before moving to the cards. They test "
                "understanding rather than recall, which the cards will cover."
            ),
        },
    },
}


def build_lesson_request(documents: list[dict], topic: dict, provider) -> dict:
    """Assemble the request that teaches one topic."""
    claims = topic.get("claims") or []
    instruction = (
        f"Teach one topic, and only this one: {topic['path']}\n\n"
        "Write it for somebody who has the material in front of them and has not "
        "understood it yet. They will be given flashcards on this topic "
        "afterwards; your job is to make those cards a reminder of something "
        "they already grasp rather than a set of facts to memorise cold.\n\n"
        "Explain mechanisms, not labels. Where the material states that "
        "something happens, say why it happens.\n\n"
        f"Difficulty: {str(topic.get('difficulty', 'medium')).lower()}. Pitch the "
        "depth to that, but never the clarity.\n\n"
        "Cover only this topic. Other topics in this deck are being taught "
        "separately, and teaching the same point twice reaches the reader as a "
        "contradiction rather than as repetition."
        + (
            "\n\nThis topic owns these points and only these:\n"
            + "\n".join(f"- {claim}" for claim in claims)
            if claims
            else ""
        )
    )
    # Five minutes rather than an hour, for the same reason pass 2 uses it: every
    # topic's lesson call sends this same schema, so they share a prefix and run
    # back to back with no human pause between them. An hour costs 2x base input
    # against 1.25x for five minutes.
    return provider.build_request(
        system=SYSTEM,
        documents=documents,
        instruction=instruction,
        schema=LESSON_SCHEMA,
        max_tokens=16000,
        cache="5m",
    )
