"""Getting source material in front of the model, and deciding what it costs.

The admission gate measures tokens, not pages. Pages are the wrong unit twice
over: several accepted formats have no page count at all, and a page is billed
as extracted text *and* a rendered image, so two documents with the same page
count can differ several-fold in cost.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from app import conversion

# Beyond this the job is refused. The context window is 1M; the rest is headroom
# for the plan, the cards, and the thinking that produces them.
TOKEN_CEILING = 700_000

# Anything at or above this is uploaded rather than inlined. A request is capped
# at 32MB whatever the context window allows, and the Files API is the only way
# past it.
INLINE_LIMIT_BYTES = 256 * 1024

FILES_BETA = "files-api-2025-04-14"

# Hardcoded rather than fetched: a price that silently changes underneath a
# budget check is worse than one that is visibly stale. claude-opus-5, USD per
# million tokens.
INPUT_PER_MTOK = 5.00
OUTPUT_PER_MTOK = 25.00
CACHE_WRITE_MULTIPLIER = 2.0  # 1-hour TTL
CACHE_READ_MULTIPLIER = 0.1

# What an estimate assumes before a plan exists to count.
ASSUMED_TOPICS = 8
ASSUMED_OUTPUT_TOKENS = 15_000

INLINE_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".text"}


class TooLarge(Exception):
    """The job costs more than the ceiling allows."""

    def __init__(self, input_tokens: int):
        self.input_tokens = input_tokens
        super().__init__(
            f"This job measures {input_tokens:,} input tokens, over the "
            f"{TOKEN_CEILING:,} limit. Remove a file or split the job."
        )


def media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def is_inline_text(path: Path) -> bool:
    return path.suffix.lower() in INLINE_TEXT_SUFFIXES


def text_document(text: str, filename: str) -> dict:
    return {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": text},
        "title": filename,
    }


def file_document(file_id: str, filename: str) -> dict:
    return {
        "type": "document",
        "source": {"type": "file", "file_id": file_id},
        "title": filename,
    }


def upload_source(provider, path: Path, filename: str) -> str | None:
    """Put one source in front of the model, returning its handle.

    None means this provider inlines the file instead of uploading it.
    """
    return provider.upload(path, filename)


def image_block(path: Path) -> dict:
    import base64

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type(path),
            "data": base64.standard_b64encode(path.read_bytes()).decode(),
        },
    }


def readable_path(source, workdir: Path, converted: dict[str, str]) -> Path:
    """The file the model will actually be shown.

    Documents and presentations are converted to PDF once and the result is
    remembered: converting again on a resume would produce different bytes, and
    the cached prefix would stop matching.
    """
    path = Path(source.stored_path)
    if not conversion.needs_conversion(path):
        return path
    already = converted.get(source.filename)
    if already and Path(already).exists():
        return Path(already)
    produced = conversion.convert_to_pdf(path, workdir)
    converted[source.filename] = str(produced)
    return produced


def document_blocks(
    provider,
    sources,
    uploaded_ids: dict[str, str] | None = None,
    converted: dict[str, str] | None = None,
    workdir: Path | None = None,
) -> list[dict]:
    """Assemble the document blocks for a job's sources.

    Small text goes inline; spreadsheets become Markdown tables; images go as
    images; everything else is uploaded once and referenced by id.
    """
    uploaded_ids = uploaded_ids if uploaded_ids is not None else {}
    converted = converted if converted is not None else {}
    blocks = []
    for source in sources:
        original = Path(source.stored_path)
        if conversion.is_spreadsheet(original):
            # Read as tables, never rendered to pages: as text it is billed once
            # and it reads better.
            markdown = conversion.spreadsheet_to_markdown(original)
            scratch = original.with_suffix(".md")
            scratch.write_text(markdown)
            blocks.append(
                provider.document_block(path=scratch, filename=source.filename, handle=None)
            )
            continue

        path = readable_path(source, workdir or original.parent, converted)
        handle = uploaded_ids.get(source.filename)
        if handle is None:
            handle = upload_source(provider, path, source.filename)
            if handle is not None:
                uploaded_ids[source.filename] = handle
        blocks.append(
            provider.document_block(path=path, filename=source.filename, handle=handle)
        )
    return blocks


# The same effort on both passes. Effort sits outside the tools -> system ->
# messages prefix the cache is keyed on, so in principle it could differ — but
# that has not been confirmed against the live API, and the cost of being wrong
# is every topic call silently paying full price. Pinned until it is verified.
EFFORT = "high"

CACHE_BREAKPOINT = {"type": "ephemeral", "ttl": "1h"}


def with_cache_breakpoint(documents: list[dict]) -> list[dict]:
    """Mark the end of the shared prefix.

    Exactly one breakpoint, on the last document. Caching is a prefix match, so
    marking earlier blocks caches strictly less while spending one of the four
    breakpoints a request is allowed. The one-hour life is what carries the
    cache across a human-length pause at the plan checkpoint.
    """
    if not documents:
        return documents
    marked = [dict(block) for block in documents]
    marked[-1]["cache_control"] = dict(CACHE_BREAKPOINT)
    return marked


def count_input_tokens(provider, request: dict) -> int:
    """Measure the exact request that is about to be sent.

    Counted over the assembled request rather than over the raw bytes, so what
    the gate measures and what the vendor bills are the same thing.
    """
    return provider.count_input_tokens(request)


def cost_of(call: dict, prices=None) -> float:
    """Price one recorded call against the hardcoded table.

    Uncached input at full rate, cache writes at the 1-hour multiplier, cache
    reads at a tenth, output at the output rate.
    """
    if prices is None:
        # The rates the job was actually billed at. Falls back to the default
        # provider's card when a caller has not supplied one.
        from app.providers.anthropic_provider import MODELS

        prices = MODELS["claude-opus-5"]
    per = 1_000_000
    return round(
        call["input_tokens"] * prices.input / per
        + call["cache_creation_input_tokens"] * prices.cache_write / per
        + call["cache_read_input_tokens"] * prices.cache_read / per
        + call["output_tokens"] * prices.output / per,
        6,
    )


# Every topic is both taught and drilled, and the two are separate calls with
# separate JSON schemas -- which means separate prompt-cache lineages, each
# needing its own write before the rest of its calls can read. Quoting one pass
# when two will run is a quote that is wrong by half, at the exact moment
# somebody is deciding whether to spend it.
PASSES_PER_TOPIC = 2


def estimate_cost(
    input_tokens: int,
    *,
    topics: int = ASSUMED_TOPICS,
    passes_per_topic: int = PASSES_PER_TOPIC,
) -> float:
    """What a job of this size is expected to cost, end to end.

    Each pass writes the document into the cache once and then reads it for
    every topic. That read multiplier is the whole reason a pass shares a prefix
    with itself — at full price, a topic fan-out would cost more than the plan
    did — and the reason the write is counted per pass rather than once: two
    schemas cannot share one cache entry.
    """
    per_pass_write = input_tokens * CACHE_WRITE_MULTIPLIER * INPUT_PER_MTOK / 1_000_000
    per_pass_reads = topics * input_tokens * CACHE_READ_MULTIPLIER * INPUT_PER_MTOK / 1_000_000
    output = passes_per_topic * ASSUMED_OUTPUT_TOKENS * OUTPUT_PER_MTOK / 1_000_000
    return round(passes_per_topic * (per_pass_write + per_pass_reads) + output, 4)
