# M2.6.4–6: complete publication, RRF and Docker retrieval

2026-09-26. Baseline 7a542df; current work is uncommitted. This accepts PDF
retrieval, not generation, numeric tools or the complete M2 answer loop.

## Implementation and controlled acceptance

- Single backend gateway/scheduler shared by ingestion/query. The official local
  tokenizer is checked before use; no runtime download or local model weights.
- Normalized 1024-dimensional float32 vectors, ordered evidence mapping and
  versioned metadata/digest persist in SQLite. Each document uses IndexFlatIP.
  Artifact, FTS replacement and ready status commit in one transaction, after
  validation/index construction. No lifecycle lock during model/quota waits.
- Restart verifies artifacts and rebuilds FAISS/FTS without parsing or embedding.
  Failed/corrupt/interrupted data cannot be queried; retry replaces document rows
  while retaining reusable content/configuration cache entries.
- Scoped global top20 lexical and top20 semantic lists, equal RRF k60, default8.
  Stable source ties include the candidate boundary. Duplicate content in separate
  uploads stays separate. Absent route ranks/scores are null. No semantic-error
  fallback and no score-as-confidence claim.

Windows and Linux: **190 tests + 10 subtests passed**. Eleven new step4–6 cases
cover paused publication/offline restore, duplicate sources, empty lexical list,
global candidate cuts/ties, scope-before-provider, failed embedding and retry,
old ready queries during quota wait, explicit query failure, two stored-corruption
cases, identical restored scores, shutdown rejecting late results, and missing
tokenizer with safe startup/error. Existing CSV/FTS/Embedding/lifecycle tests remain
green. First publication and first fusion tests were run red before wiring.
Both platforms use locked dependencies; no production code changed after these checks.

Browser: 2 new real PDF checks passed (initial 42.5 seconds including browser
startup, restart 1.6 seconds), plus 10 existing controlled UI/real proxy checks.
The general browser run skipped 5 opt-in live scenarios; the 2 PDF scenarios
were run separately. Old M2.4 PDF-failure and M2.5 real CSV ingestion scenarios
were not rerun; CSV backend regression was. Node reported only the existing
NO_COLOR/FORCE_COLOR environment warning.

## Real development material and provider budget

Only manifest development **rondel** used: SHA256
78a20a04658b46ad947eccce4d96e08f757f348e721b0d8159e5f9f1b7bff561.
Both original pages rendered and visually checked. Two pages, 17 evidence rows,
one retained layout_uncertain warning (page2); coverage extracted1/degraded1.
Not an accuracy/completeness metric. Conservative per-row preflight1380 tokens;
gateway deduplicated two identical retrieval texts, embedding15 unique inputs.

Isolated Compose project siteco-m26-acceptance, backend18090/frontend18091,
runtime D:/Projects/Retrieval_SITECO/tmp/m26-docker/runtime. Browser upload returned
202/queued; ready arrived about1.52 seconds after reception. Evidence selection,
all17 preview rows, source page numbers, refresh, warnings and zero browser page
errors passed. This supplements the M2.4 deferred real PDF successful preview.

Exactly **3 provider calls** in this part: one document batch and two queries.
Usage980 +31 +13 tokens; starts spaced20.038 and20.004 seconds. No retry or paid
switch. No generation calls. Prior steps1–3 had2 separate synthetic calls, making
5 total M2.6 calls to date. Key read only by the opt-in deployment helper and
injected into backend environment; not printed, written to artifacts or images.

## Route-specific development observations

Only D06 and D07 were executed; no held-out question, answer or record was used.
Candidate sizes/weights/k were fixed before the run and not tuned afterward.

- **D06**, compare0MD5307L1830 and0MD5307L0940: page2 order-variants evidence
  fcccf729… has lexical rank1, semantic rank1, fused rank1. Both original rows
  and their source table context are retained; visual original confirms their
  different CCT/flux/load and common ON/OFF/1.6kg. No comparison answer generated.
- **D07**, Rondel HF movement sensor part number: page2 accessories evidence
  f73a2519… has lexical rank2, semantic rank1, fused rank1. It contains the
  sensor row and5MD53003S, agreeing with original page2. Lexical rank1 is a
  page1 marketing paragraph mentioning the sensor without its part number;
  fusion promotes the required table to first. No generated answer evaluated.
- Both runs produced17 semantic candidates and8 final records. Generic headings
  and unrelated passages still occupy some final positions (e.g. D06 title-only
  evidence ranks3/4). Record this as candidate noise for later development eval;
  do not infer precision or tune on just these two queries. Ordinary OR terms,
  page title context and shared corpus BM25 statistics can contribute.
- Bounding boxes may enclose table plus original page heading. Individual
  source/context spans are more precise for later highlighting. Existing
  uncertain layout and rotated footer noise remain parser limitations.

## Restart and final running state

Temporary acceptance-only routes execute retrieval inside the owning backend;
live SQLite is never read by a host/second process. After backend recreation,
the harness forbade provider calls. Both cached questions returned identical
full results (text, locator, route scores/ranks, RRF ranks), status stayed identical,
and provider attempts were **zero**. New process timestamp verified a real restart.

The backend was recreated once more using only production compose configuration.
Acceptance route404, health200 and original ready document persisted. Test
harness remains an opt-in source file, excluded from runtime build; no production
query HTTP endpoint was added. Old M2.5 18089 and M2.4 18087 deployments remain
unchanged. Ignored screenshots/raw result JSON live under tmp/m26-docker.

## Remaining scope and risks

P-027 records structured LLM conditions → validated deterministic tools for M2.7.
No strict PDF numeric predicate, unit conversion, answer generation or source
highlighting is implemented here. Chat composer stays disabled. Retrieval always
returns nearest semantic neighbors; M2.7 must judge support and read warnings.
Small development-PDF acceptance is not large-corpus latency/recall validation.
Full vector scans and FTS rebuild at startup trade simplicity for bounded memory/
startup work; current file/page limits remain. Shared account usage outside this
backend may still cause429. Current nginx synchronous timeout120s is shorter than
the admission wait180s; M2.7 needs a deliberate pending/streaming chat transport,
not an assumption that the acceptance-only synchronous route solves long waits.
