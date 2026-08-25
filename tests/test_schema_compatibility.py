"""Our JSON schemas, checked against what the API actually accepts.

Every other test drives a scripted Claude, so a schema the real API would
reject passes all of them and fails only in front of a user — which is
exactly how a `minItems: 2` reached a live run and stopped generation dead
on the first topic. These rules come from the structured-output API's own
error messages; they cost nothing to check and they only get discovered
the expensive way.
"""

import pytest

from app.generation import CARDS_SCHEMA
from app.lessons import LESSON_SCHEMA
from app.planning import DECK_PLAN_SCHEMA

SCHEMAS = {
    "plan": DECK_PLAN_SCHEMA,
    "cards": CARDS_SCHEMA,
    "lesson": LESSON_SCHEMA,
}


def walk(node, path="$"):
    """Every subschema, with the path that reaches it."""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]")


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_array_bounds_the_api_rejects_never_appear(name):
    """minItems above 1 and maxItems at any value are both refused by the
    API — each one found the expensive way, a live 400 mid-generation."""
    offenders = []
    for path, node in walk(SCHEMAS[name]):
        if not isinstance(node, dict):
            continue
        if node.get("minItems") not in (None, 0, 1):
            offenders.append(f"{path}: minItems={node['minItems']}")
        if "maxItems" in node:
            offenders.append(f"{path}: maxItems={node['maxItems']}")
    assert not offenders, (
        "the API rejects these; state counts in the description instead:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_every_object_is_closed_and_declares_what_it_requires(name):
    """`additionalProperties: false` plus a `required` naming every property
    is what makes a structured reply predictable rather than merely likely."""
    problems = []
    for path, node in walk(SCHEMAS[name]):
        if not isinstance(node, dict) or node.get("type") != "object":
            continue
        if node.get("additionalProperties") is not False:
            problems.append(f"{path}: additionalProperties is not false")
        properties = set(node.get("properties") or {})
        if properties and set(node.get("required") or []) != properties:
            missing = properties - set(node.get("required") or [])
            problems.append(f"{path}: not required: {sorted(missing)}")
    assert not problems, "\n".join(problems)
