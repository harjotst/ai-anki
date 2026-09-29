# 18 — Image Occlusion

**What to build:** Masked-label cards for diagrams. The note type itself is stock and cheap to emit, but coordinates are not: pages rasterized during normal document handling are resized server-side at dimensions we do not control, so returned coordinates cannot be mapped back. Occlusion therefore needs its own ingestion path.

**Blocked by:** 12 — Card review; 10 — Deck sophistication

**Status:** done — 8 tests; the stock notetype round-trips through a real Anki collection

> Two masks produce two cards in Anki 26.08.1, with `originalStockKind = 6` accepted.
>
> Not built: the drag-to-adjust mask editor. Anthropic documents coordinate output as
> approximate, so some masks will be visibly off. Anki's own note editor is the fallback —
> these are genuine stock occlusion notes, so the user can nudge the shapes there. Worth
> building the editor once you see how far off real diagrams actually are.

- [x] Diagram pages are rasterized locally rather than relying on server-side document rasterization
- [x] Images are pre-resized to the high-resolution tier bounds before being sent
- [x] Coordinates are requested as absolute pixels and normalised in our own code against the pre-resize dimensions, never requested pre-normalised
- [x] The stock Image Occlusion note type is emitted with the correct stock kind and field layout, since Anki identifies it by that alone and not by name
- [x] The rasterized image used to derive coordinates is the one bundled as media, so masks align with what the user sees
- [x] Masks can be dragged and resized before download, because coordinate output is documented as approximate
- [x] The Anki contract harness asserts the note is recognised as an image occlusion note and produces one card per shape
