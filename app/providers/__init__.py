"""The model vendor, behind one narrow interface.

OpenAI is the only vendor. The interface stays because it is what keeps
request shapes, caching, refusals and prices out of the rest of the code.
"""

from __future__ import annotations

import os

from app.providers.base import (
    Capabilities,
    Prices,
    Provider,
    RateLimited,
    Reply,
    Unusable,
    Usage,
    check_usable,
)
from app.providers.openai_provider import DEFAULT_MODEL, OpenAIProvider

__all__ = [
    "Capabilities", "Prices", "Provider", "RateLimited", "Reply", "Unusable",
    "Usage", "check_usable", "build", "OpenAIProvider",
]


def build(model: str | None = None, client=None) -> Provider:
    """Construct the OpenAI provider.

    `AI_ANKI_MODEL` picks among the priced OpenAI models; an unpriced one is
    refused rather than billed at a guess.
    """
    model = model or os.environ.get("AI_ANKI_MODEL") or DEFAULT_MODEL
    if client is None:  # pragma: no cover - exercised only with the real SDK
        import openai

        client = openai.OpenAI()
    return OpenAIProvider(client, model=model)
