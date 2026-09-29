# 09 — Cache layout & cost accounting

**What to build:** The cost model made real and then verified. Caching only works if both passes share a byte-identical prefix, and parallel calls on a cold prefix all miss — so this ticket fixes the request layout, enforces the sequencing, and proves with persisted usage data that reads actually happen.

**Blocked by:** 07 — PDF ingestion and admission gate

**Status:** done — 6 tests; prefix identity, one 1h breakpoint, usage persisted, cost derived from it

> Note: `effort` is pinned identical across both passes. It sits outside the
> tools -> system -> messages prefix the cache keys on, so it could in principle differ,
> but that is unconfirmed against the live API and the downside is every topic call
> silently paying full price. Relax only after a live check.

- [x] The system prompt is pass-agnostic and byte-identical across both passes
- [x] Document blocks come first in the user message, with a one-hour cache breakpoint on the last of them
- [x] Pass-specific instructions appear after the breakpoint and never in the system prompt
- [x] Tool definitions, effort and thinking configuration are identical across passes
- [x] The generation fan-out begins only after the planning pass has completed, since a cache entry becomes readable only once the first response begins
- [x] Per-call usage is persisted, including cache creation and cache read token counts
- [x] A test asserts generation calls record non-zero cache reads and zero cache creation
- [x] Job cost is computed from persisted usage against a hardcoded price table
