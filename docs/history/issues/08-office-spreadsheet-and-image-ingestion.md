# 08 — Office, spreadsheet & image ingestion

**What to build:** The remaining input formats. Documents and presentations convert to PDF so one internal format flows downstream; spreadsheets become tables because rendering them as pages reads worse and costs more; images and plain text pass through. The conversion step has a silent failure mode that must be designed against, not discovered.

**Blocked by:** 07 — PDF ingestion and admission gate; 03 — Deploy the skeleton

**Status:** done — 7 tests, all passing inside the container image (671MB)

> The two that matter only run in the container and are wired into CI: a real LibreOffice
> conversion, and a 6-way concurrent batch producing all 6 PDFs. With a shared user profile
> that batch yields ~2 PDFs and ~4 silent exit-1s with no diagnostic output at all.

- [x] Documents and presentations convert to PDF via headless conversion
- [x] Every conversion receives a fresh temporary user-installation profile — a shared profile does not serialise, it fails silently with no diagnostic output
- [x] Concurrent conversions are bounded by a semaphore sized to available processors, kept separate from the generation fan-out limit
- [x] A conversion that produces no output fails the job with a message naming the specific file, rather than continuing silently
- [x] Spreadsheets extract to Markdown tables rather than being rendered to pages
- [x] Images and plain-text formats are accepted
- [x] Files upload one at a time with per-file progress and per-file failure
- [x] Fonts required by common office documents are present in the image
- [x] A test converts real fixture files inside the container, including a concurrent batch, asserting every expected output is produced
