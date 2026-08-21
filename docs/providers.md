# Model providers

## Switching

Two environment variables. No code change, no redeploy of anything but config.

```bash
fly secrets set --stage AI_ANKI_PROVIDER=anthropic AI_ANKI_MODEL=claude-sonnet-5
```

Supported today: `anthropic` (default) and `gemini`. An unknown name is refused
rather than silently falling back — a silent fallback is how you get a bill from
the vendor you thought you had left.

## The gate

A provider is checked at startup, not discovered mid-job. Three requirements,
and failing any one is disqualifying regardless of price:

| Requirement | Why it is a gate |
|---|---|
| Caching that lasts ≥ 20 min | Pass 2 makes N calls each re-reading the whole document. Without a cache that survives the user reading the plan, the document is paid for once per topic — roughly **3–4× the bill** on every provider measured. |
| Native document input | Sources are PDFs, slides and scans. There is deliberately no OCR stage to fall back on. |
| Schema-enforced JSON | Both passes parse strict JSON. Best-effort JSON mode is not the same guarantee. |

This is what rules out most of the cheap end. Verified 2026-08-17:

- **Cohere** — no prompt caching product at all.
- **DeepSeek** — no vision.
- **Qwen** — 5-minute cache TTL that resets. Will not survive the plan checkpoint.
- **Meta Llama** (Together / Groq / Fireworks / DeepInfra) — no caching on any host.
- **Amazon Nova** — caching capped at **20,000 tokens**, ~10% of a typical document. The cache saves 0.7%.

## Rates

Hardcoded per provider with the date each was verified, never fetched. A price
that changes silently underneath a budget check is worse than one that is
visibly stale.

| Model | In | Out | Cache write | Cache read | Modelled job* |
|---|---:|---:|---:|---:|---:|
| `claude-opus-5` | $5.00 | $25.00 | $10.00 | $0.50 | $3.15 |
| `claude-sonnet-5` | $2.00 | $10.00 | $4.00 | $0.20 | $0.96 |
| `gemini-3.7-flash` | $0.75 | $3.75 | $0.75 | $0.075 | $0.34 |
| `gemini-3.1-flash-lite` | $0.25 | $1.50 | $0.25 | $0.025 | $0.14 |

\* 200k-token document, 1 planning call + 8 topic calls, 14k output.

**Two dated cliffs.** `claude-sonnet-5` introductory pricing ends **2026-08-31**
($2/$10 → $3/$15). Gemini Flash introductory pricing ends **2027-01-01** and
every rate doubles, including cache storage.

## Two things that are assumptions, not facts

**Google publishes no cache-write multiplier** — not on the pricing page, the
caching page, or the `cachedContents` reference. `cache_write` is set equal to
`input` on the Gemini models, and `CACHE_WRITE_IS_ASSUMED` marks it. Measure it
on a real job before trusting a budget.

**Gemini bills a PDF page at 258 tokens flat and does not charge for natively
extracted text.** For born-digital slides that is far below a token estimate.
For a dense *scan* it is one fixed-resolution image per page, and may not
resolve text that a higher-fidelity render would. The cost advantage and the
quality risk are the same fact seen from two sides. `media_resolution` is the
lever; test it on real scans before switching.

## Choosing on evidence rather than sticker price

Cost per job is objective and is in the table. Cost per *usable* card is not,
and that is the number that matters — a model at a fifth of the price that has
40% of its cards rejected is worse value and wastes the user's review time.

One proxy worth knowing: measured hallucination rates run **Sonnet 5 at 39.4%,
Gemini 3.7 Flash at 64.5%, the GPT-5.6 family at 90–92%**. That is general
knowledge, not card generation — but a flashcard is memorised deliberately on a
spaced schedule, so confabulation costs more here than almost anywhere.

The app already instruments the real answer: `api_call` rows give cost per job,
and the review screen's reject and edit actions give the acceptance rate. Run
the same documents through two providers and compute it.
