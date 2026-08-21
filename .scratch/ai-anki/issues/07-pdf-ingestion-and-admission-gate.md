# 07 — PDF ingestion & admission gate

**What to build:** Real PDFs, and a size gate that measures the thing that actually costs money. Page count is rejected as the unit: it does not exist for several accepted formats and does not predict cost, because every page is billed as extracted text *and* a rendered image.

**Blocked by:** 01 — Walking skeleton

**Status:** done — 8 tests; gate measures tokens over the assembled request, never pages

- [x] A PDF upload is stored, sent to the Files API, and referenced by identifier in generation requests
- [x] The required Files API beta header is sent both on upload and on every request referencing the file
- [x] Token counting runs over the exact assembled request, after conversion and before the planning pass
- [x] Jobs above the token ceiling are rejected before any generation spend, showing the measured count
- [x] The API returns the measured token count and an estimated cost computed from a hardcoded price table
- [x] The user-facing size contract is tokens and currency; page count is never presented as the limit
- [x] Scanned PDFs produce cards, with no OCR stage anywhere in the pipeline
