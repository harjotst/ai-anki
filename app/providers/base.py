"""What the rest of the application is allowed to know about a model vendor.

The interface is deliberately narrow. Everything that differs between vendors —
how a document is attached, how caching is expressed, how JSON is constrained,
how a refusal is signalled, what tokens cost — sits behind it, because those are
exactly the things that do not generalise.

Three capabilities are hard requirements for this workload, and a provider that
cannot do all three is not cheaper, it is unusable:

  * caching that survives a human pause at the plan checkpoint. Without it the
    document is paid for once per topic call instead of once per job.
  * native document input. The sources are PDFs, slides and scans, and there is
    deliberately no OCR stage.
  * schema-enforced JSON. Both passes parse strict JSON; best-effort JSON mode
    is not the same guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


class Unusable(Exception):
    """The model answered, but the answer cannot be used.

    Refusals, truncation and unparseable output all land here, so a caller never
    has to know how a particular vendor signals them.
    """


class RateLimited(Exception):
    """The vendor said not yet, and usually said when.

    Distinct from Unusable because the correct response is opposite: an
    Unusable call is recorded and given up on, a rate-limited one is worth
    exactly one thing — waiting. Observed live 2026-08-26: a five-topic
    fan-out of 64k-token calls against a 200k-TPM organization limit failed
    two topics that a 20-second pause would have carried.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class Usage:
    """What one call cost, as the vendor reported it."""

    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class Reply:
    data: dict
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class Prices:
    """USD per million tokens. Hardcoded per provider, never fetched.

    A price that changes silently underneath a budget check is worse than one
    that is visibly stale, so every rate here carries the date it was verified.
    """

    input: float
    output: float
    cache_write: float
    cache_read: float
    verified_on: str
    storage_per_mtok_hour: float = 0.0

    def cost(self, usage: Usage, *, cache_hours: float = 0.0) -> float:
        per = 1_000_000
        return round(
            usage.input_tokens * self.input / per
            + usage.cache_write_tokens * self.cache_write / per
            + usage.cache_read_tokens * self.cache_read / per
            + usage.output_tokens * self.output / per
            # Only Google rents cached content by the hour; it is zero elsewhere.
            + (usage.cache_write_tokens / per) * cache_hours * self.storage_per_mtok_hour,
            6,
        )


@dataclass(frozen=True)
class Capabilities:
    """Declared, and checked at startup rather than discovered in production."""

    caching: bool
    cache_survives_minutes: int
    native_documents: bool
    strict_schema: bool
    max_input_tokens: int


@runtime_checkable
class Provider(Protocol):
    name: str
    model: str
    prices: Prices
    capabilities: Capabilities

    def upload(self, path: Path, filename: str) -> str | None:
        """Put a source where the model can read it, returning a handle.

        Returning None means the provider inlines this file instead.
        """

    def document_block(self, *, path: Path, filename: str, handle: str | None) -> dict:
        """One source, in whatever shape this vendor's request wants."""

    def build_request(
        self,
        *,
        system: str,
        documents: list[dict],
        instruction: str,
        schema: dict,
        max_tokens: int,
        cache: str | None = None,
    ) -> dict:
        """Assemble a JSON-constrained request, optionally caching the prefix.

        Documents go first and the instruction last, so calls sharing a schema
        share one cacheable prefix.

        `cache` is the lifetime to ask for ("5m", "1h") or None for no caching.
        None is the right answer more often than it looks: a cache entry nothing
        reads still costs a write premium, so caching is only worth it when a
        *later* call will share this exact prefix.
        """

    def count_input_tokens(self, request: dict) -> int:
        """Measure the exact request that is about to be sent."""

    def send(self, request: dict) -> Reply:
        """Send it, and raise `Unusable` rather than returning something broken."""


# The gate every provider must pass before it is allowed to run a job. A pause
# at the plan checkpoint is a human reading a table, so a cache that expires in
# five minutes does not survive it.
MINIMUM_CACHE_MINUTES = 20


def check_usable(provider: Provider) -> list[str]:
    """Why this provider cannot serve this workload, if it cannot."""
    c = provider.capabilities
    problems = []
    if not c.caching:
        problems.append(
            "no prompt caching: the document would be paid for once per topic call"
        )
    elif c.cache_survives_minutes < MINIMUM_CACHE_MINUTES:
        problems.append(
            f"cache lasts only {c.cache_survives_minutes} minutes, which will not "
            "survive a user editing the plan"
        )
    if not c.native_documents:
        problems.append("no native document input, and there is no OCR stage to fall back on")
    if not c.strict_schema:
        problems.append("no schema-enforced JSON; both passes parse strict JSON")
    return problems
