# M2.8 task/chat and clean Docker smoke

2026-09-27. Baseline 29b308978783d3f214174900eb1ed84f1919b4cf plus current working
tree. This is M2.8's two-path smoke, not M3's multi-document/state/failure matrix or
the final M2 Standards/Spec review.

## Controlled checks and build

- Windows: 261 tests + 10 subtests passed, 44.31s.
- Linux Docker test target: 261 tests + 10 subtests passed, 36.79s.
- Final static Docker frontend: 13 browser tests passed, 5 historical opt-in real
  tests skipped (11.8s); separate new real two-path smoke passed (31.7s).
- Frontend TypeScript/Vite build and both Docker runtime builds passed. A backend
  one-off tokenizer command downloaded/verified the pinned public JSON from scratch.
- Task tests use real SQLite, actual HTTP and controlled external models/time:
  frozen scope/schema validation before model calls, idempotency/conflict, other
  conversation rejection, bounded queue, timeout while provider is blocked,
  late publication prevention, shutdown/restart interruption, result restoration,
  model-free CSV paging, responsive health/upload/poll during model waiting.
- Browser tests cover sending, quota status, citations, refresh without POST,
  manual same-request recovery, timeout versus insufficient evidence, partial
  answer warnings/omissions/withheld segments and duplicate CSV source pagination.

## Fresh runtime procedure

First runtime: tmp/m28-docker/runtime, Compose siteco-m28-acceptance, ports18092/18093.
Final runtime: tmp/m28-clean/runtime, Compose siteco-m28-smoke, ports18094/18095.
Both directories were newly created, never copied from a development runtime.
The Docker startup sequence built the normal images, ran tokenizer preparation,
then started two healthy services. Keys were read locally and injected only into
backend runtime environment. There were no special acceptance routes or mounted
test adapters. Browser asserted an empty document list before uploading.

Original authorized Rondel PDF and price-list CSV were uploaded using browser file
controls. No eval answer file was loaded; no old database, index, vectors or query
cache was reused. Each question selected only its newly uploaded document. New
conversation separated PDF and CSV. Original page/record evidence supplied the
manual correctness check; no held-out question or paid-plan change.

## Results and retained failure

First smoke: PDF succeeded, CSV incorrectly returned needs_clarification via an
empty plan. The test failed instead of counting this as success. PDF upload-to-ready
2.288s, question20.772s; CSV upload2.605s, failed-quality question1.130s. Reports and
screenshots remain in tmp/m28-docker; that project's containers were stopped, data
retained. This repeats the M2.7 planning failure and was not hidden by automatic retry.

Diagnosis checked the model planning seam. A single probe on the same failed question
and metadata added generic instructions distinguishing JSON planning from SDK function
calls, and order existence from identifier extraction. It produced the exact lookup.
The production prompt now says explicit product/article/order identifiers for prices
or validity dates must be looked up even when their existence is unknown. No actual
order ID, filename, price or date is hardcoded in the prompt. This addresses a
plausible ambiguity; one probe and smoke are not proof of general routing reliability.

The final smoke started from a second empty runtime after the change:

- PDF: ready2.344s, question20.693s, answered. Returned order0MD5307L1830:
  colour temperature3.000K, connected load18W, weight1,6kg. S1 resolves to the
  order-variants table on physical page2, with original headings and layout warning.
  Original page and rendered browser source were checked. This is parameter listing,
  not a numerical calculation or a broadened PDF ownership grammar.
- CSV: ready2.453s, question3.177s, answered. Order51DB11EC11B1D: Listenpreis183,20,
  gültig ab01.06.2026. S1 resolves to logical record1 with original fields. Browser
  opened the source, displayed matching-record paging (1–1 of1) and restored the
  answer after refresh without resubmitting. No inferred currency/tax/discount.

Final document IDs: PDF7758b95074074557b8bd2a4b72ef4237;
CSV eeb7e731107d4759b3dd1d84f0c870ab. Final task IDs:
0d2fa01f4d514452aeb7d4e90532bf98 and ad75feb0632e4a34bbfed7b228e804c7.
Reports: tmp/m28-clean/browser-results.json, empty.png, pdf-answer.png, csv-answer.png.
All are ignored local artifacts, not bundled into an image.

## Calls, waiting and credentials

Final deployment logged Voyage document980tokens/0.808s and query36tokens/0.339s;
Gemini PDF answer1.791s, CSV plan1.051s and CSV answer1.335s. Model is
gemini-3.5-flash-lite; embeddings remain voyage-4/1024. Browser observed quota wait
for about16.8s (1.5s polling granularity), followed by retrieving/generating/completed.
The 20.7s PDF task was dominated by shared minimum-call-spacing, not slow generation.

First deployment logged Voyage980+36tokens, durations0.819/0.367s, Gemini PDF1.751s
and CSV plan0.835s. Including the one direct planning probe, this increment made
4 Voyage calls (2032tokens total) and6 Gemini calls; no provider call failed or retried
in these logs. One returned plan failed the answer-quality check. No live Groq call.
Task timings include browser polling overhead and are not an SLA.

Build context remains an allowlist. Local comparison against supplied key values
found none in final image configuration/history or copied frontend static assets;
the frontend container has no provider-key environment variables. Image runtime
source is copied only from backend/app; neither root key files nor runtime data is
copied. Credentials are never passed as build arguments or written into frontend
variables. Sanitized provider logs record phase/status/duration/usage only.

The final preview stays at http://127.0.0.1:18095/; backend18094. Both containers are
healthy. Older M2.6 preview18091 remains unchanged. Runtime data stays on D; Docker
images/cache stay in their existing C-drive location. Live SQLite was accessed only
by the backend; inspection used HTTP and container logs.

## Remaining limits

24h temporary tasks and per-tab recovery are not persistent conversation history.
Conversation identifiers isolate demo behavior but do not implement authentication.
One worker can remain occupied until a timed-out socket call returns; queueing is
bounded and the task terminal state remains final. No SSE, multi-turn reference
resolution, OCR, vision or source highlighting was added. Semantic answer correctness
still requires source verification. M2.9 fixed-scope Standards/Spec review and M3
multi-document/state/failure matrix remain separate work.
