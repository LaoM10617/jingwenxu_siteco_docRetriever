# M2.5: CSV parsing, durable exact lookup and Docker acceptance

2026-09-26. Parser `price-list-v1`; baseline commit `047ccf9` plus the
uncommitted M2.5 implementation. Steps 1–3 were accepted first; the separate
steps 4–6 checkpoint below adds durable lookup and real ready acceptance.
No model calls were used in either checkpoint.

## Results

- Windows and Linux: 37 CSV parser tests pass. Full regression on each platform:
  106 tests plus 10 subtests pass, with the existing Starlette/httpx warning.
- TDD slices: source/record test failed on unsupported CSV, then passed;
  structural tests failed on missing validation, then passed; money/duplicate
  tests failed on unsafe conversion and missing warnings, then passed.
- Full manifest CSV: 11,386 logical records, 18 columns, all decoded raw cells
  and record positions preserved, unique evidence IDs, repeat parsing stable,
  zero warnings. Semantic checks are limited to development records 1 and 2.
- First measured parse: Windows 0.0651s, Linux 0.1219s. These are individual
  local observations including file hashing, not comparative benchmarks, query
  latency claims, or maximum-volume guarantees. Disk cache conditions differ.
- Fixed schema, BOM support, quoted delimiters/quotes/newlines, empty fields,
  missing/trimmed/duplicate order keys, exact 20,000-record success and 20,001
  failure verified with synthetic data. Structural errors return no partial result.
- Synthetic money cases verify comma decimals, dot grouping, signs, zero,
  whitespace, high precision, missing and invalid values. Missing/invalid values
  retain raw content, yield None rather than zero and carry record warnings.
  Scientific notation, currency text, decimal dots and non-ASCII numeric forms
  are not silently interpreted as supported German price values.

## Reproduce

From the repository root:

```powershell
& ./backend/.venv/Scripts/python.exe -m pytest -q
& ./backend/.venv/Scripts/python.exe eval/check_m25_csv.py
docker build --target test -t siteco-backend:m25-csv-test -f backend/Dockerfile .
docker run --rm --network none --mount "type=bind,source=D:/Projects/Retrieval_SITECO/data/Price Lists/leuchten_siteco_LPR_2026_06.csv,target=/app/input/prices.csv,readonly" --mount "type=bind,source=D:/Projects/Retrieval_SITECO/eval/check_m25_csv.py,target=/app/eval/check_m25_csv.py,readonly" siteco-backend:m25-csv-test python /app/eval/check_m25_csv.py /app/input/prices.csv
```

No raw materials enter the image; the Linux sample check mounts only the CSV
and checker read-only. The checker verifies the manifest hash, parses the full
file and never loads held-out questions. It does not print reserved row values.

## Matching limitations and follow-up register

Steps 4–6 tested real lookup for development records 1 and 2 and a clearly absent
sentinel only. Both expected records were returned, with no wrong match or lost
source observed. This is not a general matching-quality score or latency benchmark.

- Known deliberate behavior: case, inner spaces, hyphens and leading zeros remain
  significant. A differently typed ID may therefore miss an otherwise intended
  order. No real user-query miss is claimed here; preserve exact matching until
  an observed case justifies a separately reviewed change.
- Outer-space normalization can produce duplicate keys. Synthetic acceptance
  verifies collision warnings and preservation of both original rows, not merging.
- Unsupported price forms remain raw/invalid. A later query can still return the
  record, but numerical comparison must explicitly exclude unavailable amounts
  and report their count/reason rather than silently treating them as zero.
- Empty-key records are retained but unsearchable by order. If a future file has
  such rows, document summaries must expose the limitation independently of LLM
  wording. Step 4 makes entirely empty-key files fail csv_no_order_ids with a
  retained summary/warnings, rather than claiming ready. Mixed files retain all
  evidence rows while excluding missing keys from exact order matching.
- Changed/reordered headers, encodings or CSV dialects are outside this confirmed
  limited importer. The default standard-library per-field size limit applies.

For later observed failures record: development-case identifier or sanitized
input, selected document IDs, expected record positions, actual matches/counts,
failure layer (parse/normalization/scope/lookup/pagination/generation), reproduction
and proposed change. Do not use held-out rows as optimization examples.

## Steps 4–6 acceptance

- Windows and Linux full regression: 132 tests + 10 subtests passed on each;
  one existing Starlette/httpx deprecation warning. The first real CSV lifecycle
  test failed with processing_not_configured before the adapter was implemented.
  Subsequent scope/fault/pagination tests are acceptance and regression tests;
  not every test in this checkpoint was written before implementation.
- SQLite stores per-document records, an exact BINARY order index and immutable
  snapshot metadata/digest. Decimal strings remain lossless, including synthetic
  high precision; raw columns remain strings. Status loads summaries only.
- Tests cover staged records hidden from both evidence and lookup, already-ready
  documents remaining readable, failure after staging, retry without duplicate
  accumulation, stop blocking late publication, corrupt/missing snapshots rejected
  on restart, retry recovery and restoration without parsing/provider calls.
- T-006 tests cover all-or-error scope, unselected documents excluded, same-order
  rows across uploads retained, same-filename sources identified by document ID,
  query order/dedup, explicit unmatched IDs, exact case/spacing/punctuation/zeros,
  SQL-like IDs treated literally, 2,000 absent query keys, invalid arguments and
  pagination. A 205-duplicate fixture is read in 100/100/5 pages without omission,
  retaining multiline quoted text, record numbers and exact high-precision prices.
- Windows and Linux frontend TypeScript/production builds passed. Edge/Playwright:
  9 controlled UI tests, 1 real CSV upload/lookup test, 1 container-recreation test
  and 1 real nginx proxy test passed (12 distinct tests). The earlier real PDF
  upload test was not rerun in this checkpoint; backend PDF regressions were.
- Real Docker upload via file input: fixed manifest CSV hash
  b58bcea0e2d5c1e9f0017a25d3f1153bf75c25c0e78dd02a9a711ceb699483b9;
  HTTP 202 queued → ready, 11,386 records, all with order IDs, zero warnings.
  Browser selection, source pages 1/2 and refresh verified. No reserved rows were
  queried/displayed, and no held-out answer file was read.
- The acceptance-only route called lookup_orders in the owning backend process.
  Development orders 51DB11EC11B1D and 51DB11EC11D1D matched records 1/2 with
  price string 183.20. NOT-A-SITECO-ORDER-000 returned explicitly unmatched.
  Total=2 with two limit=1 pages; after backend force-recreation, status and both
  results matched the saved responses exactly. Running SQLite was never opened
  externally. No provider SDK/model call participates in CSV ingestion or restore.
- After verification, recreated the backend using production Compose alone.
  Acceptance route returns 404; real CSV remains ready. Proxy health/404/415/413
  checks passed against the production router. No test harness enters the image.

Observed limitations/follow-ups (no policy change made):

- Synthetic differently-cased/zero-stripped/space-altered keys miss, as required by
  the exact contract. They are not silently replaced with near products. A real
  user-intent mismatch remains unobserved; log examples before revising matching.
- The source viewer displays 20 full records per page, which is long for an
  18-column price list. It is usable but dense; a compact result table belongs to
  the later chat/result presentation work, not a new query UI in this checkpoint.
- Query results expose all matches through paging, but this build has no chatbot
  narration, complete-match table in chat, aggregation or user clarification flow.
  Those cannot be counted as accepted just because the deterministic query passed.

## Reproduce Docker/browser steps 4–6

Use an isolated runtime and the test-only override, from the project root:

```powershell
$env:HOST_PORT='18088'
$env:FRONTEND_PORT='18089'
$env:HOST_DATA_DIR='D:/Projects/Retrieval_SITECO/tmp/m25-acceptance/runtime'
docker compose -p siteco-m25-acceptance -f compose.yaml -f eval/m25-acceptance.compose.yaml up -d --build --wait
$env:M24_BASE_URL='http://127.0.0.1:18089'
$env:M25_CSV='D:/Projects/Retrieval_SITECO/data/Price Lists/leuchten_siteco_LPR_2026_06.csv'
npm test --prefix frontend -- --grep 'upload complete file'
Remove-Item Env:M25_CSV
docker compose -p siteco-m25-acceptance -f compose.yaml -f eval/m25-acceptance.compose.yaml up -d --force-recreate --no-deps --wait backend
$env:M25_RESTART='1'
npm test --prefix frontend -- --grep 'same exact results'
Remove-Item Env:M25_RESTART
docker compose -p siteco-m25-acceptance -f compose.yaml up -d --force-recreate --no-deps --wait backend
$env:M24_REAL_PROXY='1'
npm test --prefix frontend -- --grep 'real proxy'
```

Each upload consumes a document slot; use a fresh isolated runtime for repeated
acceptance runs. Artifacts are ignored under tmp/m25-acceptance: browser-result.json
(development records only), csv-evidence.png and csv-viewport.png. The M2.5 preview
uses frontend18089/backend18088; the earlier M2.4 preview18087 is a separate old
deployment. Runtime data stays on D:, Docker images/cache stay on C:.
