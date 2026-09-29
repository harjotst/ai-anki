# 17 — Spend controls

**What to build:** Bounded spend at every layer. A single large job is a meaningful amount of money, and the application must be able to refuse work it knows is too expensive rather than relying solely on a backstop that kills everyone at once.

**Blocked by:** 09 — Cache layout and cost accounting; 04 — Invite tokens and sessions

**Status:** done — 8 tests; four layers, with the Console cap documented as the outer backstop

- [x] A per-job token ceiling is enforced at admission and re-checked before the generation fan-out
- [x] A rolling 24-hour per-user budget blocks further jobs once exceeded
- [x] A global daily ceiling halts the worker
- [x] An environment-variable kill switch stops all generation without a redeploy
- [x] Spend is attributable per invite token and visible to the owner
- [x] Exceeding any budget produces a clear message naming which limit was hit
- [x] Documentation records the provider-side monthly cap as the outer backstop that survives application bugs
