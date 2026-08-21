"""Google Gemini. The cheap alternative, and the one worth measuring against.

Two things make it attractive for this workload specifically, and one makes it
risky.

Attractive: every Flash tier is FLAT-priced with no context tier break, where
Gemini Pro, OpenAI and xAI all double past a threshold this app routinely
crosses. And Gemini 3 does not bill natively-extracted PDF text at all — a page
costs 258 image tokens whatever is written on it, which for a born-digital
lecture deck is far below what a token estimate would suggest.

Risky: that same 258 tokens is one fixed-resolution image per page. On a dense
SCAN — the photocopied-chapter case this app exists for — it may simply not
resolve the text, where a provider rendering the page at higher fidelity would.
`media_resolution` is the lever, and it wants measuring on real material.
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from app.providers.base import Capabilities, Prices, Reply, Unusable, Usage


def _seconds(lifetime: str) -> int:
    """"5m" / "1h" as seconds."""
    value, unit = int(lifetime[:-1]), lifetime[-1]
    return value * (60 if unit == "m" else 3600)

MODELS = {
    # Verified 2026-08-17 against ai.google.dev/pricing.
    # WARNING: this is INTRODUCTORY pricing. On 2027-01-01 every one of these
    # doubles — input, output, cached read AND storage. Budget for $1.50/$7.50.
    "gemini-3.7-flash": Prices(
        0.75, 3.75, 0.75, 0.075, verified_on="2026-08-17", storage_per_mtok_hour=0.50
    ),
    "gemini-3.1-flash-lite": Prices(
        0.25, 1.50, 0.25, 0.025, verified_on="2026-08-17", storage_per_mtok_hour=1.00
    ),
    # Flat across the whole range, unlike the Pro tiers.
    "gemini-3.5-flash": Prices(
        1.50, 9.00, 1.50, 0.150, verified_on="2026-08-17", storage_per_mtok_hour=1.00
    ),
}

# Google publishes NO cache-write multiplier anywhere — not on the pricing page,
# the caching page, or the cachedContents reference. Creation is assumed to bill
# at plain input rate, which is why cache_write == input above. This is an
# assumption, not a fact: measure it on a real job before trusting a budget.
CACHE_WRITE_IS_ASSUMED = True


class GeminiProvider:
    name = "gemini"

    def __init__(self, client, model: str = "gemini-3.7-flash", cache_ttl_seconds: int = 3600):
        if model not in MODELS:
            raise ValueError(f"unpriced model {model!r}; add it to MODELS with a verified rate")
        self._client = client
        self.model = model
        self._ttl = cache_ttl_seconds
        self.prices = MODELS[model]
        self.capabilities = Capabilities(
            caching=True,
            # Explicit `cachedContents` with a caller-set TTL. Implicit caching
            # exists and is free to store, but hits are best-effort — which is
            # not good enough when the whole cost model rests on them.
            cache_survives_minutes=cache_ttl_seconds // 60,
            native_documents=True,
            strict_schema=True,
            max_input_tokens=700_000,
        )

    def upload(self, path: Path, filename: str) -> str | None:
        uploaded = self._client.files.upload(
            file=str(path),
            config={"mime_type": mimetypes.guess_type(filename)[0] or "application/pdf"},
        )
        return uploaded.uri

    def document_block(self, *, path: Path, filename: str, handle: str | None) -> dict:
        if handle is not None:
            return {
                "file_data": {
                    "file_uri": handle,
                    "mime_type": mimetypes.guess_type(filename)[0] or "application/pdf",
                }
            }
        return {"text": path.read_text()}

    def build_request(
        self, *, system, documents, instruction, schema, max_tokens, cache=None
    ) -> dict:
        # Documents first, instruction last, so every call in a job shares one
        # cacheable prefix — the same discipline as the Anthropic path, spelled
        # differently.
        return {
            "model": self.model,
            "contents": [{"role": "user", "parts": [*documents, {"text": instruction}]}],
            "config": {
                "system_instruction": system,
                "max_output_tokens": max_tokens,
                "response_mime_type": "application/json",
                "response_json_schema": schema,
                # Explicit rather than implicit: it converts a probabilistic
                # discount into a guaranteed one, and storage rent is ~5% of
                # what the cached reads save.
                **(
                    {"cached_content_ttl_seconds": _seconds(cache)} if cache else {}
                ),
            },
        }

    def count_input_tokens(self, request: dict) -> int:
        return self._client.models.count_tokens(
            model=request["model"], contents=request["contents"]
        ).total_tokens

    def send(self, request: dict) -> Reply:
        response = self._client.models.generate_content(
            model=request["model"], contents=request["contents"], config=request["config"]
        )
        return Reply(data=self._read(response), usage=self._usage(response))

    @staticmethod
    def _usage(response) -> Usage:
        u = getattr(response, "usage_metadata", None)
        cached = getattr(u, "cached_content_token_count", 0) or 0
        prompt = getattr(u, "prompt_token_count", 0) or 0
        return Usage(
            # Gemini reports the cached portion inside the prompt count, so the
            # uncached remainder has to be derived rather than read off.
            input_tokens=max(0, prompt - cached),
            cache_read_tokens=cached,
            output_tokens=getattr(u, "candidates_token_count", 0) or 0,
        )

    @staticmethod
    def _read(response) -> dict:
        finish = getattr(response, "candidates", None)
        reason = getattr(finish[0], "finish_reason", None) if finish else None
        if reason and str(reason).upper().endswith("SAFETY"):
            raise Unusable(
                "Gemini declined this material on safety grounds. This can happen with "
                "medical or life-sciences content even when the request is legitimate."
            )
        if reason and str(reason).upper().endswith("MAX_TOKENS"):
            raise Unusable(
                "Gemini ran out of room before finishing, so the response is truncated "
                "and cannot be parsed."
            )
        text = getattr(response, "text", None)
        if not text:
            raise Unusable(f"Gemini returned no text to parse (finish_reason: {reason}).")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise Unusable(f"Gemini returned text that is not valid JSON: {exc}") from exc
