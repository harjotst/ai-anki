"""Getting source material in front of the model, and deciding what it costs.

The admission gate measures tokens, not pages. Pages are the wrong unit twice
over: several accepted formats have no page count at all, and a page is billed
as extracted text *and* a rendered image, so two documents with the same page
count can differ several-fold in cost.
"""

from __future__ import annotations

from pathlib import Path

from app import conversion

# Beyond this the job is refused. The context window is 1M; the rest is headroom
# for the plan, the cards, and the thinking that produces them.
TOKEN_CEILING = 700_000

# What an estimate assumes before a plan exists to count.
ASSUMED_TOPICS = 8
ASSUMED_OUTPUT_TOKENS = 15_000


class TooLarge(Exception):
    """The job costs more than the ceiling allows."""

    def __init__(self, input_tokens: int):
        self.input_tokens = input_tokens
        super().__init__(
            f"This job measures {input_tokens:,} input tokens, over the "
            f"{TOKEN_CEILING:,} limit. Remove a file or split the job."
        )


def upload_source(provider, path: Path, filename: str) -> str | None:
    """Put one source in front of the model, returning its handle.

    None means this provider inlines the file instead of uploading it.
    """
    return provider.upload(path, filename)


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


def count_input_tokens(provider, request: dict) -> int:
    """Measure the exact request that is about to be sent.

    Counted over the assembled request rather than over the raw bytes, so what
    the gate measures and what the vendor bills are the same thing.
    """
    return provider.count_input_tokens(request)


def cost_of(call: dict, prices=None) -> float:
    """Price one recorded call against the hardcoded table.

    Uncached input at full rate, cache writes and reads at their own rates,
    output at the output rate.
    """
    if prices is None:
        # The rates the job was actually billed at. Falls back to the default
        # model's card when a caller has not supplied one.
        from app.providers.openai_provider import DEFAULT_MODEL, MODELS

        prices = MODELS[DEFAULT_MODEL]
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
    prices=None,
) -> float:
    """What a job of this size is expected to cost, end to end.

    Each pass writes the document into the cache once and then reads it for
    every topic. That read multiplier is the whole reason a pass shares a prefix
    with itself — at full price, a topic fan-out would cost more than the plan
    did — and the reason the write is counted per pass rather than once: two
    schemas cannot share one cache entry.

    Priced from the model that will actually run the job, never from a
    separate hardcoded table that can drift from it.
    """
    if prices is None:
        from app.providers.openai_provider import DEFAULT_MODEL, MODELS

        prices = MODELS[DEFAULT_MODEL]
    per = 1_000_000
    per_pass_write = input_tokens * prices.cache_write / per
    per_pass_reads = topics * input_tokens * prices.cache_read / per
    output = passes_per_topic * ASSUMED_OUTPUT_TOKENS * prices.output / per
    return round(passes_per_topic * (per_pass_write + per_pass_reads) + output, 4)
