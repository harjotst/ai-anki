"""Model vendors, behind one narrow interface.

`build(...)` is the only place that knows which vendors exist.
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

__all__ = [
    "Capabilities", "Prices", "Provider", "RateLimited", "Reply", "Unusable",
    "Usage", "check_usable", "build", "PROVIDERS",
]

PROVIDERS = ("anthropic", "gemini", "openai")


def build(name: str | None = None, model: str | None = None, client=None) -> Provider:
    """Construct the configured provider.

    Reads the environment so that swapping vendors is a redeploy, not a code
    change — and refuses an unknown name rather than silently falling back to a
    default the operator did not ask for.
    """
    name = (name or os.environ.get("AI_ANKI_PROVIDER") or "anthropic").lower()
    model = model or os.environ.get("AI_ANKI_MODEL") or None

    if name == "anthropic":
        import anthropic

        from app.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(client or anthropic.Anthropic(), model=model or "claude-sonnet-5")

    if name == "gemini":
        from app.providers.gemini_provider import GeminiProvider

        if client is None:  # pragma: no cover - exercised only with the real SDK
            from google import genai

            client = genai.Client()
        return GeminiProvider(client, model=model or "gemini-3.7-flash")

    if name == "openai":
        from app.providers.openai_provider import OpenAIProvider

        if client is None:  # pragma: no cover - exercised only with the real SDK
            import openai

            client = openai.OpenAI()
        return OpenAIProvider(client, model=model or "gpt-5.6-luna")

    raise ValueError(f"unknown provider {name!r}; expected one of {', '.join(PROVIDERS)}")
