# 11 — Plan editor

**What to build:** The first human checkpoint, and the one that controls spend. The user sees what the model understood and what it will cost before anything expensive runs, and can correct the structure rather than accept it.

**Blocked by:** 07 — PDF ingestion and admission gate; 05 — Job state machine

**Status:** done — 7 API tests at the HTTP seam; React plan editor built and served

> Scope note, stated plainly: the behaviour is tested at Seam 1 (the HTTP boundary) —
> editing, validation, rejection, re-roll, billing, the rendered cloze, the download
> guidance. The React components themselves have **no test suite**. Adding one would be
> a third seam, which we agreed not to introduce. The UI has been built and served but
> not driven by a browser, so treat its interactions as unverified.

- [x] The plan shows per-topic difficulty, rationale, assigned claims, note type and proposed card count
- [x] Card counts, titles, deck paths and note types are editable, and topics can be deleted
- [x] Measured token count and estimated cost are shown before approval
- [x] Approving moves the job into generation; nothing expensive runs before approval
- [x] A plan can be left and returned to via its own URL
- [x] Edits are validated server-side, including bounds the response schema cannot express, since numeric constraints are unsupported there
