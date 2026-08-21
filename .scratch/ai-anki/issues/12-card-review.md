# 12 — Card review

**What to build:** The quality checkpoint. Nothing reaches the user's collection unread. A bad card is worse than a missing one — it gets drilled for weeks before anyone notices — so this screen is where the product earns trust.

**Blocked by:** 06 — Live progress; 11 — Plan editor

**Status:** done — 7 API tests at the HTTP seam; React review screen built and served

> Scope note, stated plainly: the behaviour is tested at Seam 1 (the HTTP boundary) —
> editing, validation, rejection, re-roll, billing, the rendered cloze, the download
> guidance. The React components themselves have **no test suite**. Adding one would be
> a third seam, which we agreed not to introduce. The UI has been built and served but
> not driven by a browser, so treat its interactions as unverified.

- [x] Cards appear per topic as each generation call completes
- [x] Cloze cards render as they will appear rather than as raw markup
- [x] Inline editing, deletion, re-rolling a single card, regenerating a whole topic, and bulk rejection by topic all work
- [x] Re-roll and regenerate reuse the existing generation path and record their own usage
- [x] Nothing enters the package until it is accepted
- [x] The download page shows the job's tag search string so a bad batch can be found and removed in Anki
- [x] The download page states that Anki's import defaults are already correct and should be left alone
