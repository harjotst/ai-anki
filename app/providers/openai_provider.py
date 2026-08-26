"""OpenAI, via the Responses API. The budget option.

GPT-5.6 Luna is priced an order of magnitude under Sonnet 5 on this workload
— $0.20/$1.20 per MTok against $2/$10 — which is the whole reason this module
exists. Every request shape here was verified against the versioned developer
docs on 2026-08-26: `input_file` document parts, `text.format` structured
outputs with `strict: true`, and explicit prompt caching via
`prompt_cache_options` with per-part `prompt_cache_breakpoint` markers.

Caching differs from Anthropic in two load-bearing ways. The only supported
TTL on GPT-5.6+ is "30m" — there is no one-hour tier, so a request asking for
"1h" gets thirty minutes and the capability declaration says so. And writes
bill at 1.25x the input rate against Anthropic's 2x, while reads are 0.1x on
both — the fan-out economics that make a topic run affordable carry over.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

import openai

from app.providers.anthropic_provider import (
    INLINE_LIMIT_BYTES,
    INLINE_TEXT_SUFFIXES,
    estimate_document_tokens,
)
from app.providers.base import Capabilities, Prices, Reply, Unusable, Usage

MODELS = {
    # Verified 2026-08-26 against developers.openai.com/api/docs/models and
    # /docs/guides/prompt-caching. Launched 2026-07-09; input/output cut 80%
    # on 2026-07-30. Cache write is 1.25x input, cache read 0.1x input.
    "gpt-5.6-luna": Prices(0.20, 1.20, 0.25, 0.02, verified_on="2026-08-26"),
}

# The only TTL GPT-5.6+ accepts, and how long a prefix survives after its
# last use. Above the app's 20-minute floor; nowhere near Anthropic's hour.
CACHE_TTL = "30m"


class OpenAIProvider:
    name = "openai"

    def __init__(self, client, model: str = "gpt-5.6-luna"):
        if model not in MODELS:
            raise ValueError(f"unpriced model {model!r}; add it to MODELS with a verified rate")
        self._client = client
        self.model = model
        # file_id -> local path, for the admission gate: there is no OpenAI
        # token-counting endpoint at all, so uploaded documents are estimated
        # from their page count rather than measured.
        self._local: dict[str, Path] = {}
        self.prices = MODELS[model]
        self.capabilities = Capabilities(
            caching=True,
            cache_survives_minutes=30,
            native_documents=True,
            strict_schema=True,
            max_input_tokens=700_000,
        )

    def upload(self, path: Path, filename: str) -> str | None:
        if path.suffix.lower() in INLINE_TEXT_SUFFIXES and path.stat().st_size < INLINE_LIMIT_BYTES:
            return None
        uploaded = self._client.files.create(
            file=(filename, path.read_bytes(), mimetypes.guess_type(filename)[0] or "application/pdf"),
            purpose="user_data",
        )
        self._local[uploaded.id] = path
        return uploaded.id

    def document_block(self, *, path: Path, filename: str, handle: str | None) -> dict:
        if handle is not None:
            return {"type": "input_file", "file_id": handle}
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            mime = mimetypes.guess_type(filename)[0] or "image/png"
            data = base64.standard_b64encode(path.read_bytes()).decode()
            return {"type": "input_image", "image_url": f"data:{mime};base64,{data}"}
        return {"type": "input_text", "text": path.read_text()}

    def build_request(
        self, *, system, documents, instruction, schema, max_tokens, cache=None
    ) -> dict:
        # Same discipline as the other vendors, spelled OpenAI's way: documents
        # first and the instruction last, with exactly one cache breakpoint on
        # the last document — and only when a later call will actually read it.
        # `mode: "explicit"` turns the automatic best-effort caching into the
        # guaranteed kind the cost model rests on.
        marked = [dict(block) for block in documents]
        request: dict = {
            "model": self.model,
            "max_output_tokens": max_tokens,
            "instructions": system,
            "input": [
                {"role": "user", "content": [*marked, {"type": "input_text", "text": instruction}]}
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "reply",
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        if marked and cache:
            marked[-1]["prompt_cache_breakpoint"] = {"mode": "explicit"}
            request["prompt_cache_options"] = {"mode": "explicit", "ttl": CACHE_TTL}
        return request

    def count_input_tokens(self, request: dict) -> int:
        """Measure what can be measured, estimate the rest.

        OpenAI has no token-counting endpoint, so text is counted locally with
        the tokenizer family GPT-5.6 uses and documents are estimated from
        their page count — deliberately pessimistically, because the gate this
        feeds refuses jobs, and over-estimating is the cheaper mistake.
        """
        import tiktoken

        encoding = tiktoken.get_encoding("o200k_base")
        counted = len(encoding.encode(request.get("instructions") or ""))
        estimated = 0
        for message in request.get("input", []):
            for block in message.get("content", []):
                if block.get("type") == "input_text":
                    counted += len(encoding.encode(block.get("text") or ""))
                elif block.get("type") == "input_file":
                    estimated += estimate_document_tokens(self._local.get(block.get("file_id")))
                elif block.get("type") == "input_image":
                    estimated += 1_600
        return counted + estimated

    def send(self, request: dict) -> Reply:
        try:
            response = self._client.responses.create(**request)
        except openai.OpenAIError as exc:
            # The SDK has already retried what is worth retrying. Raised raw,
            # this strands the job in whatever running state claimed it;
            # Unusable is the shape every caller fails-and-records on.
            raise Unusable(f"OpenAI could not serve this call: {exc}") from exc
        return Reply(data=self._read(response), usage=self._usage(response))

    @staticmethod
    def _usage(response) -> Usage:
        u = getattr(response, "usage", None)
        details = getattr(u, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        written = getattr(details, "cache_write_tokens", 0) or 0
        total_input = getattr(u, "input_tokens", 0) or 0
        return Usage(
            # OpenAI reports cached and written tokens inside the input count,
            # so the plain-rate remainder is derived rather than read off —
            # the same arithmetic the Gemini path does.
            input_tokens=max(0, total_input - cached - written),
            cache_write_tokens=written,
            cache_read_tokens=cached,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
        )

    @staticmethod
    def _read(response) -> dict:
        status = getattr(response, "status", None)
        if status == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            if reason == "max_output_tokens":
                raise Unusable(
                    "OpenAI ran out of room before finishing (incomplete: "
                    "max_output_tokens), so the response is truncated and cannot "
                    "be parsed."
                )
            raise Unusable(f"OpenAI returned an incomplete response ({reason}).")

        for item in getattr(response, "output", None) or []:
            for block in getattr(item, "content", None) or []:
                if getattr(block, "type", None) == "refusal":
                    raise Unusable(
                        f"OpenAI declined this material: {getattr(block, 'refusal', '')} "
                        "This can happen with medical or life-sciences content even "
                        "when the request is legitimate."
                    )

        text = getattr(response, "output_text", None)
        if not text:
            raise Unusable("OpenAI returned no text to parse.")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise Unusable(f"OpenAI returned text that is not valid JSON: {exc}") from exc
