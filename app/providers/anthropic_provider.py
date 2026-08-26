"""Anthropic. The reference implementation, and the current default.

Everything here was verified against the SDK's generated types and, where it
mattered, against a live Anki round-trip: the plain-text document source, the
`output_config` carrying effort and format together, and `fallbacks: "default"`.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

import anthropic

from app.providers.base import Capabilities, Prices, Reply, Unusable, Usage

FILES_BETA = "files-api-2025-04-14"
# On a policy decline the API re-runs the request on a fallback model inside the
# same call. Study material in medicine and the life sciences sits close enough
# to the safety classifiers that this is worth having on by default.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Which models accept the `fallbacks` parameter at all. Opus 5 accepts it
# (verified live 2026-08-17); Sonnet 5 refuses the whole request with a 400 —
# "'claude-sonnet-5' does not support the `fallbacks` parameter" (verified live
# 2026-08-26, req_011CeQfD9jcBcLEpdiDRjox7, a planning run it took down).
FALLBACK_MODELS = frozenset({"claude-opus-5"})

# Anything at or above this is uploaded rather than inlined: a request is capped
# at 32MB whatever the context window allows.
INLINE_LIMIT_BYTES = 256 * 1024
INLINE_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".text"}

MODELS = {
    # Verified 2026-08-17 against platform.claude.com/docs/en/about-claude/pricing.
    # 1-hour cache write is 2x base input; cache hits are 0.1x.
    "claude-opus-5": Prices(5.00, 25.00, 10.00, 0.50, verified_on="2026-08-17"),
    # 2.2x cheaper than Opus 5 on this workload for an identical request shape.
    # NOTE: $2/$10 is introductory and rises to $3/$15 on 2026-09-01, which puts
    # cache_write at $6.00 and cache_read at $0.30.
    "claude-sonnet-5": Prices(2.00, 10.00, 4.00, 0.20, verified_on="2026-08-17"),
}


# Claude renders every PDF page as BOTH extracted text and an image, and bills
# both: roughly 1,500-3,000 text tokens plus up to 4,784 visual tokens per page.
# Used only when a document cannot be inlined for exact counting.
TOKENS_PER_PAGE_ESTIMATE = 5_000


def estimate_document_tokens(path: Path | None) -> int:
    """A deliberately pessimistic stand-in for a document we cannot count exactly.

    Over-estimating turns away a job that might have fitted; under-estimating
    lets through one that cannot run and bills for the attempt. The first is
    the cheaper mistake.
    """
    if path is None or not path.exists():
        return TOKENS_PER_PAGE_ESTIMATE * 40
    if path.suffix.lower() == ".pdf":
        try:
            import pypdfium2

            document = pypdfium2.PdfDocument(str(path))
            try:
                return len(document) * TOKENS_PER_PAGE_ESTIMATE
            finally:
                document.close()
        except Exception:
            pass
    # Fall back on size. Rough, and meant to be.
    return max(1, path.stat().st_size // 400)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client, model: str = "claude-sonnet-5", effort: str = "high"):
        if model not in MODELS:
            raise ValueError(f"unpriced model {model!r}; add it to MODELS with a verified rate")
        self._client = client
        self.model = model
        self._effort = effort
        # file_id -> the local file it came from. The token-counting endpoint
        # rejects file sources outright, so counting has to be done against an
        # inlined copy of the same bytes. Populated on upload; empty in a
        # process that did not do the uploading, which is why the fallback
        # below exists.
        self._local: dict[str, Path] = {}
        self.prices = MODELS[model]
        self.capabilities = Capabilities(
            caching=True,
            # Explicit 1-hour breakpoint, which is what lets the plan checkpoint
            # be a human reading a table rather than a race.
            cache_survives_minutes=60,
            native_documents=True,
            strict_schema=True,
            max_input_tokens=700_000,
        )

    def upload(self, path: Path, filename: str) -> str | None:
        if path.suffix.lower() in INLINE_TEXT_SUFFIXES and path.stat().st_size < INLINE_LIMIT_BYTES:
            return None
        file_id = self._client.beta.files.upload(
            file=(filename, path.read_bytes(), mimetypes.guess_type(filename)[0] or "application/pdf"),
        ).id
        self._local[file_id] = path
        return file_id

    def document_block(self, *, path: Path, filename: str, handle: str | None) -> dict:
        if handle is not None:
            return {"type": "document", "source": {"type": "file", "file_id": handle}, "title": filename}
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mimetypes.guess_type(filename)[0] or "image/png",
                    "data": base64.standard_b64encode(path.read_bytes()).decode(),
                },
            }
        return {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": path.read_text()},
            "title": filename,
        }

    def build_request(
        self, *, system, documents, instruction, schema, max_tokens, cache=None
    ) -> dict:
        # Exactly one breakpoint, on the last document, and only when a later
        # call will actually read it. MEASURED 2026-08-17 against the live API:
        # structured outputs render ahead of the messages, so two calls sending
        # DIFFERENT json schemas get different cache lineages no matter how
        # identical their documents are. The planning pass therefore shares with
        # nothing, and caching it would buy a write premium and no reads.
        marked = [dict(block) for block in documents]
        if marked and cache:
            marked[-1]["cache_control"] = {"type": "ephemeral", "ttl": cache}
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "output_config": {
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": schema},
            },
            "messages": [
                {"role": "user", "content": [*marked, {"type": "text", "text": instruction}]}
            ],
        }

    # A base64 document inflates by 4/3, and the whole request is capped at
    # 32MB. Anything above this is counted by estimate instead.
    COUNTABLE_LIMIT_BYTES = 20 * 1024 * 1024

    def count_input_tokens(self, request: dict) -> int:
        """Measure the request that is about to be sent.

        The token-counting endpoint refuses `file` sources — "File sources are
        not supported in the token counting endpoint" — so every uploaded
        document is swapped for an inlined copy of the same bytes. Identical
        content, identical count, a transport the endpoint will accept.
        """
        countable, estimated = self._inline_for_counting(request["messages"])
        measured = self._client.beta.messages.count_tokens(
            model=request["model"],
            system=request["system"],
            messages=countable,
            betas=[FILES_BETA],
        ).input_tokens
        return measured + estimated

    def _inline_for_counting(self, messages: list[dict]) -> tuple[list[dict], int]:
        """Swap file references for inline bytes, estimating what cannot be swapped.

        Returns the countable messages and the token estimate for any document
        that could not be inlined — a file this process did not upload (a
        resumed job) or one too large to inline.
        """
        estimated = 0
        rebuilt = []
        for message in messages:
            content = []
            for block in message.get("content", []):
                source = block.get("source") if isinstance(block, dict) else None
                if not (source and source.get("type") == "file"):
                    content.append(block)
                    continue

                path = self._local.get(source["file_id"])
                if path is None or not path.exists() or path.stat().st_size > self.COUNTABLE_LIMIT_BYTES:
                    estimated += estimate_document_tokens(path)
                    continue

                content.append({
                    **block,
                    "source": {
                        "type": "base64",
                        "media_type": mimetypes.guess_type(path.name)[0] or "application/pdf",
                        "data": base64.standard_b64encode(path.read_bytes()).decode(),
                    },
                })
            rebuilt.append({**message, "content": content})
        return rebuilt, estimated

    def send(self, request: dict) -> Reply:
        betas = [FILES_BETA]
        extra: dict = {}
        if self.model in FALLBACK_MODELS:
            betas.insert(0, FALLBACK_BETA)
            extra["fallbacks"] = "default"
        try:
            response = self._client.beta.messages.create(
                **request, betas=betas, **extra
            )
        except anthropic.APIError as exc:
            # The SDK has already retried whatever was worth retrying. Raised
            # raw, this strands the job in whatever running state claimed it;
            # Unusable is the shape every caller fails-and-records on.
            raise Unusable(f"Anthropic could not serve this call: {exc}") from exc
        return Reply(data=self._read(response), usage=self._usage(response))

    @staticmethod
    def _usage(response) -> Usage:
        u = getattr(response, "usage", None)
        return Usage(
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
        )

    @staticmethod
    def _read(response) -> dict:
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) or "unspecified"
            raise Unusable(
                f"Claude declined this material (category: {category}). This can happen "
                "with medical or life-sciences content even when the request is legitimate."
            )
        if stop == "max_tokens":
            raise Unusable(
                "Claude ran out of room before finishing (stop_reason: max_tokens), so the "
                "response is truncated and cannot be parsed."
            )
        if stop not in ("end_turn", "stop_sequence"):
            raise Unusable(f"Unexpected stop_reason: {stop}")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise Unusable("Claude returned no text block to parse.")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise Unusable(f"Claude returned text that is not valid JSON: {exc}") from exc
