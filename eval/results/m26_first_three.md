# M2.6.1–3 acceptance

2026-09-26; baseline 7a542df. User approved the recommendations and authorized
only steps 1–3. FAISS publication, executed RRF and PDF ready are still pending.

## Offline verification

- Windows/Linux final full suites: **179 tests + 10 subtests** on each platform.
  New coverage: 26 PDF scope/FTS cases, 21 embedding/quota/SDK cases. Real temporary
  SQLite, fake providers/clocks, event-driven concurrency; no keys in normal tests.
- Red/green slices: missing scope/gateway modules, missing RPM/TPM batching,
  missing retry behavior, German ß indexing mismatch, numeric-string vectors
  incorrectly accepted by float coercion. Subsequent acceptance tests supplement
  these; not every case was test-first.
- Lexical checks: full scope validation before retrieval, candidate filtering
  before top-N, duplicate uploads retain distinct document identities, original
  text/locators preserved, lower BM25 score first, replacement/reopen durability,
  leading zeros, punctuation, decimal/sign literals, German/English/diacritics,
  safe MATCH construction, empty/no-hit routes and no duplicate accumulation.
- Embeddings: order/duplicate restoration, document/query/model cache isolation,
  counts/dimension/numeric-type/finiteness/nonzero validation before cache write,
  3 RPM/10K TPM rolling budget, >=20-second spacing, prefix+margin accounting,
  <=4K batches, oversize rejection, restart budget retention, actual usage above
  reservation, query priority, bounded queue, cancellation/late result rejection,
  retry limits/deadlines and Retry-After. Cooldown is installed before waking the
  next caller. No provider/quota wait holds an application database transaction.
- SDK adapter: fixed sanitized authentication/429/timeout/server errors, both SDK
  and transport retries off, connect/read timeout 30 seconds. This is not a hard
  kill or strict total socket lifetime; blocking calls finish or time out before
  cooperative cancellation can take effect.
- One final Linux run exposed a flaky priority test: every competing thread's
  condition wait advanced the same fake clock, causing artificial expiry before
  the provider thread could finish. Replaced that test clock progression with
  controlled provider duration. The targeted test passed on both platforms and
  20 consecutive Windows runs, followed by the full final suites. No model call
  or production request was involved in this failure.

## Dependencies and actual hosted calls

- Same runtime lock installed on Windows/Linux; pip check passes. voyageai0.5.0,
  tokenizers0.23.2, faiss-cpu1.15.1; NumPy2.5.3 retained. Both platforms ran an
  independent 1024-float32 IndexFlatIP smoke (not application publication).
- Runtime closure has 69 pins. Voyage brings LangChain/LangSmith transitively;
  no application splitter/orchestration/tracing uses them. No local-model extras
  or weights installed. The old Starlette/httpx warning disappears because this
  closure includes httpx2; warnings were not suppressed and tests were not skipped.
- Only the official pinned ~7 MB voyage-4 tokenizer JSON was downloaded, on D:
  under tmp/m26-acceptance/tokenizers. Runtime loads it locally after SHA checking.
  Revision/checksum/source details: docs/m26-voyage-notes.md and app/voyage.py.
- Actual hosted calls: **exactly two**, a batch of two short synthetic documents
  then one query, separated by **20.02 seconds**. voyage-4, explicit input_type,
  1024 float32, truncation=False. No retry observed. API usage: **37 + 8 tokens**.
- Local prefix-inclusive counts were 51 and 17; with 16 safety tokens per text,
  reservations were 83 and 33. Conservative for this sample, not a general proof
  of exact provider billing. Returned dimensions/finiteness passed; nearest
  synthetic sample A was as intended, not a PDF quality benchmark.
- Fresh gateway restored arrays exactly from cache with a provider that raises
  if called. A separate **--network none** Linux container read the same stopped,
  isolated acceptance DB and tokenizer, with zero calls. Never opened the live
  backend SQLite externally. No credentials mounted into Linux or images.

## Observations and remaining scope

The German ß query mismatch was reproduced and fixed with matching NFC/casefold
rules for indexed/query text while keeping the source unchanged. Full literal
keys distinguish AB-123/AB 123, 12,5/12.5, 0012/12, -5/5 in synthetic tests.
Natural-language OR words may retrieve rows without the specified literal;
matched_literals exposes that distinction. Compact 20W vs 20 W, Unicode dash
variants, locale/unit equivalence and product/parameter ownership are not guessed.
Log real development misses before changing matching; no held-out material used.

Structured numeric operations remain a later proposal: validated LLM tool plan,
grounded fields, deterministic Decimal comparison and whitelisted unit conversion,
explicit uncertainty. No arbitrary generated code or LLM arithmetic tool added.

Production wiring is pending: shared gateway lifespan, coordinated FTS/vector/
ready publication, per-document FAISS mappings/recovery, hybrid/RRF execution and
real PDF Docker/browser retrieval. Valid retrieve currently reports
retrieval_not_configured; lexical_candidates is explicitly a lexical diagnostic.
Existing preview18089 remains M2.5 and healthy; no production container rebuild,
frontend change or browser rerun. Test image: siteco-backend:m26-test.
No billing setting changes or commit/push in this checkpoint.

## Reproduction

```powershell
& ./backend/.venv/Scripts/python.exe -m pytest -q
docker build --target test -t siteco-backend:m26-test -f backend/Dockerfile .
& ./backend/.venv/Scripts/python.exe scripts/prepare_voyage_tokenizer.py D:/Projects/Retrieval_SITECO/tmp/m26-acceptance/tokenizers
& ./backend/.venv/Scripts/python.exe eval/check_m26_embeddings.py --runtime D:/Projects/Retrieval_SITECO/tmp/m26-acceptance/embedding-runtime --tokenizer D:/Projects/Retrieval_SITECO/tmp/m26-acceptance/tokenizers/voyage-4-tokenizer.json
```

The last command requires the accepted cache and defaults to offline verification;
on cache miss it fails without a provider call. Explicit --live --key-file enables
the small hosted smoke; do not run it automatically or as a benchmark.
