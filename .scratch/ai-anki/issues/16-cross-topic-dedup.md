# 16 — Cross-topic dedup

**What to build:** Stop the same fact becoming three cards. Parallel topic calls each see the whole corpus, so overlap is the normal outcome on a multi-file job rather than an edge case. The fix is partition first, then catch the remainder.

**Blocked by:** 12 — Card review; 10 — Deck sophistication

**Status:** done — 7 tests; pass 1 partitions claims, repeats are flagged not deleted

> Semantic near-duplicates are matched on the normalised question only, not by a further
> Claude call. Exact-after-normalisation is deliberate at this layer: a false positive would
> flag two genuinely different questions as redundant, and the cost of a miss is only that
> the user reviews a fact twice. A semantic pass can be added later if partitioning proves
> insufficient on real material.

- [x] The planning pass assigns each claim to exactly one topic, and overlap is resolved before generation
- [x] Each generation call receives sibling topic titles as explicit exclusions
- [x] Exact duplicates are detected on normalised card fronts
- [x] Semantic near-duplicates are grouped by a dedicated pass over generated fronts
- [x] Duplicates are surfaced in the review screen and never removed silently
- [x] Where duplicates are collapsed, the instance kept is the one in the most specific topic
- [x] The download page advises running Anki's duplicate finder after import to catch overlap with pre-existing cards
