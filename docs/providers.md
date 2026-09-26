# The model

## OpenAI, and only OpenAI

Every pass — the plan, the lessons, the cards, a re-roll — goes to OpenAI's
Responses API. The server needs one secret:

```bash
fly secrets set OPENAI_API_KEY=sk-...
```

`AI_ANKI_MODEL` picks among the models priced in
`app/providers/openai_provider.py`; the default is `gpt-5.6-luna`. An unpriced
model is refused at startup rather than billed at a guess.

## The gate

The model is checked at startup, not discovered mid-job. Three requirements,
and failing any one is disqualifying regardless of price:

| Requirement | Why it is a gate |
|---|---|
| Caching that lasts ≥ 20 min | Pass 2 makes N calls each re-reading the whole document. Without a cache that survives the user reading the plan, the document is paid for once per topic — roughly **3–4× the bill**. |
| Native document input | Sources are PDFs, slides and scans. There is deliberately no OCR stage to fall back on. |
| Schema-enforced JSON | Every pass parses strict JSON. Best-effort JSON mode is not the same guarantee. |

GPT-5.6 passes all three: explicit prompt caching with a 30-minute TTL,
`input_file` document parts, and `text.format` structured outputs with
`strict: true`.

## Rates

Hardcoded with the date each was verified, never fetched. A price that changes
silently underneath a budget check is worse than one that is visibly stale.

| Model | In | Out | Cache write | Cache read |
|---|---:|---:|---:|---:|
| `gpt-5.6-luna` | $0.20 | $1.20 | $0.25 | $0.02 |

Per million tokens, verified 2026-08-26. The only cache TTL GPT-5.6+ accepts is
30 minutes, which is above the gate's 20.

## Two things that are estimates, not measurements

**There is no token-counting endpoint.** The admission gate counts text locally
with the o200k tokenizer and estimates each uploaded document at 5,000 tokens
per page, deliberately high: over-estimating turns away a job that might have
fitted, under-estimating lets through one that cannot run.

**Strict structured outputs reject some JSON Schema.** Every object must be
closed and list every property as required, and several numeric bounds are
refused. `tests/test_schema_compatibility.py` checks each schema the app sends,
because a scripted test cannot catch what only the live API rejects.

## Judging it on evidence

Cost per job is objective. Cost per *usable* card is not, and that is the number
that matters — a cheap model that has 40% of its cards rejected is worse value
and wastes the user's review time.

One proxy worth knowing: measured general-knowledge hallucination rates put the
GPT-5.6 family at **90–92%**, well above the other models this app
was first built on. A flashcard is memorised deliberately on a spaced schedule,
so confabulation costs more here than almost anywhere.

The app already instruments the real answer: `api_call` rows give cost per job,
and the review screen's reject and edit actions give the acceptance rate. Watch
it on real documents.
