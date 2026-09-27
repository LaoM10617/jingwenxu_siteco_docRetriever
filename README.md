# SITECO Document Retriever

The current build provides a React/TypeScript document chat and a FastAPI backend, started together with Docker Compose. Upload PDF/CSV files, wait for ready, select materials and ask a question. PDF answers use FTS5/BM25 and Voyage/FAISS retrieval; supported price-list CSVs use exact order lookup. Answers include source passages, physical page or logical record numbers, and extraction warnings. Check the source and its conditions: ready and retrieval hits do not guarantee completeness or correctness.

See [development setup](docs/development.md) for Python 3.12 environment creation, pinned dependency installation, and verification commands. See [reuse notes](docs/reuse.md) for provenance and migration boundaries.

## Reviewer entry points

- Start here for Docker commands and required credentials; the browser entry is
  **http://127.0.0.1:8080** with default ports. No hosted deployment is required.
- [Delivery guide](docs/delivery.md): source/history handover, material acquisition,
  architectural decisions, a 10-minute demo outline and remaining work.
- [Evaluation](eval/README.md): inspect the HTML report locally or recompute its
  summaries without API calls. Live reproduction requires your own keys/materials.
- [Reuse and provenance](docs/reuse.md): reused components and implementation boundaries.

## Implemented and verified scope

The current implementation supports selected-document PDF/CSV questions, mixed
scopes, asynchronous task polling, source expansion and temporary multi-turn
conversation memory. PDF retrieval combines global lexical/vector candidate lists
(20 each) with equal-weight RRF (k=60), returning up to 8 passages by default (Settings: 1–20). CSV lookup
uses exact, case-sensitive order numbers and retains duplicate source records.
History helps resolve subjects; each answer retrieves fresh evidence from the
currently selected materials. See the [retrieval contract](docs/m26-retrieval-contract.md),
[question contract](docs/m28-chat-contract.md) and [memory contract](docs/m3-memory-contract.md).

Recorded M3 verification includes Windows and Linux runs of 308 tests plus 10
subtests each, and 28 browser checks passed with 6 historical opt-in checks skipped.
These are historical results, not tests rerun by following this README. The real
four-question sequence exposed an incorrect product assignment despite valid
citations. After the fix, only two original follow-ups were rechecked successfully;
the original sequence is not reported as all passing. See the
[M3 checkpoint](eval/results/m3_checkpoint.md) and
[integration evidence](eval/results/m35_integration.md) for outcomes and limits.

M4 functionality has passed its freeze checkpoint; see the [scope, review and validation](docs/m46-feature-freeze.md). Local PDF original-page
previews with evidence/context regions and CSV record previews are implemented and
sampled against real citations; see the [M4.3 checkpoint](eval/results/m43_preview.md).
Settings supports Gemini/Groq model and in-memory Key configuration, Voyage Key configuration, Top K and reranking. See [controlled verification](eval/results/m45_settings.md); Gemini/Voyage passed one live PDF configuration check at Top K 8. Groq/Voyage passed the same question at Top K 1 after an account token-limit failure at Top K 8. See [live acceptance status](eval/results/m45_live_settings.json). The default configuration retains RRF. An
8-question prose-PDF development comparison increased required evidence in context
from 10/12 to 11/12, with complete coverage unchanged at 7/8 questions. One subsequent paired answer check recovered the missing retention rule and
exception. This is a single-case improvement, with an evidence gap still remaining;
optional reranking is implemented through Settings and a startup environment default (off by default). See the [comparison and remaining check](eval/results/m44_prose_comparison.md).
The first formal M5.0 A+B evaluation is complete: strict pass 3/12, required-fact
coverage 10/40, and default RRF evidence coverage 10/12. These small-set results
include provider failures and blocked dependent turns; they are not a general
accuracy estimate. See the [report](eval/results/m50/run-20260927-ab-01/report.md)
and [reproduction instructions](eval/README.md). A subsequently discovered
sentence-final-period validation defect has been fixed with local regression;
the original evaluation scores remain unchanged. Clean-runtime live acceptance
and final delivery are still pending. Multi-model comparison has not been run.

## Optional PDF reranking

Set `PDF_RERANK_ENABLED=true` in the backend environment (or Compose `.env`) and
recreate/restart the backend to enable fixed Voyage `rerank-2.5-lite` using the
existing `VOYAGE_API_KEY`. The default is `false`; Settings can override it in memory without restarting. Enabling it sends the question and the PDF candidate passages to Voyage and
adds usage charges. It does not affect CSV lookup.

Reranking uses the same candidate union before selecting the configured Top K sources. It has a
5-second budget within the existing question deadline, no retries, one in-flight
request and a configurable minimum interval after completion per backend process (default 20 seconds, `RERANK_MIN_INTERVAL`). Error cooldowns remain separate.
Busy/cooldown, provider errors, invalid output or timeout retain the original RRF
order and add a visible source warning. Provider timing and fallback reasons are
logged without keys or document text. A timed-out network request may finish in
the background; no additional rerank request starts until it finishes. The small
development comparison does not establish universal quality or latency gains.

## Ask questions with Docker

Use Docker Desktop with Linux containers. No host Python or Node installation is
needed for this path. From the repository root, copy `.env.example` to `.env`
without overwriting an existing configuration. Set an explicit `HOST_DATA_DIR`
(for example `D:/siteco-runtime`), free loopback ports, `GENERATION_PROVIDER=gemini`,
`GEMINI_API_KEY`, and `VOYAGE_API_KEY`. Alternatively provide the variables in the
shell environment. Groq can be selected explicitly with its own key. Keys are
passed only to the backend at runtime; never put them in frontend variables or
build arguments. Missing generation credentials produce an explicit question error.

```powershell
docker compose config --quiet
docker compose build
docker compose run --rm --no-deps backend python -m app.prepare_tokenizer /app/runtime/tokenizers
docker compose up -d --wait --wait-timeout 60
```

The one-off command downloads and checksum-verifies only the pinned public tokenizer
JSON. It does not load a model, copy an index or send documents. It exits before the
two long-running services start. Download failure is explicit; resolve network or
directory permissions and rerun the command. Runtime directory ownership must allow
the backend container user (UID 10001) to write it on Linux hosts.

Open the configured frontend port (default http://127.0.0.1:8080), upload a supported
PDF or CSV, wait for ready and select it in Materials. Ask a question with explicit
product/order numbers. The browser polls task status and shows complete answers,
partial results, clarification, exact misses and execution failures separately.
Expand each citation to inspect original text and context. CSV record browsing
does not regenerate the answer or imply it summarized all matching rows.

Follow-ups use temporary memory within the same conversation (up to 6 whole
turns / 12,000 serialized characters). New conversation clears the current turns
and selected scope. Per-tab request metadata supports refresh with GET polling,
without automatically submitting questions again. Completed turns remain available
until 24 hours after the first question; follow-ups do not extend retention.
Unfinished tasks become interrupted on backend restart and are not retried
automatically. Material selection is restored within the same tab and conversation,
then checked against the loaded ready documents. Unavailable selections are removed
with a notice; review Materials before asking. Existing tasks retain their submitted
scope. This is a single-user local demo, not an authenticated multi-user service.

Voyage ingestion/query share the configured local admission budget (defaults: 3 RPM/10K TPM). Settings shows the running limits. Waiting can dominate latency. Question
deadline is 240 seconds including queueing, with at most 60 seconds per generation
call; late answers cannot overwrite timeout. Socket I/O is cooperatively stopped,
so a timed-out worker may take time to return. Do not blindly resubmit after a
connection error: use “Check / resend same request” to retain the idempotency key.
Use a new question for a terminal failure. Uploads and ready documents remain usable.

For a clean smoke check, use a new empty HOST_DATA_DIR and a separate Compose project
(`docker compose -p siteco-smoke ...` on every command). Confirm an empty material
list; upload a PDF, ask and check its source, then start a new conversation and repeat
with a price-list CSV. Do not copy an existing database, vectors, embedding cache or
answers. A successful pair is only a basic smoke check, not the M3 acceptance matrix.

## Repository layout

Empty directories are not tracked by Git. Requirements, private materials, runtime data, and temporary files below are local-only.

```text
Retrieval_SITECO/
├── README.md                      # Entry point for operators and reviewers
├── AGENTS.md                      # Project collaboration rules
├── requirements_draft.md           # Local-only requirements notes; not in the clone
├── milestones_and_execution_plan.md
├── decisions.md                    # Confirmed choices and testing boundaries
├── .gitignore
├── .dockerignore
├── .env.example                    # Configuration example (no real keys included)
│
├── backend/                        # Backend source code, dependencies, and unit tests
│   ├── app/
│   └── tests/
│
├── frontend/                       # Frontend source code, dependencies, and unit tests
│   └── src/
│
├── tests/                          # Migrated tracing test and future cross-stack checks
│   ├── e2e/
│   └── fixtures/                   # Small, controlled test samples suitable for version control
│
├── eval/                           # Acceptance material definitions and performance checks
│   ├── materials.md                # Document sources, characteristics, and acquisition methods
│   ├── cases/                      # Questions, key answer points, and evidence locations
│   └── results/                    # Filtered acceptance records
│
├── docs/                           # Supplementary documentation
│   ├── development.md              # Development environment setup and check commands
│   └── reuse.md                    # Migration sources, modifications, dependencies, and verification
│
├── logs/                           # Manually maintained implementation records
│   ├── current.md                  # Standard handover entry point
│   └── m0.md                      # Phase-specific records (as needed)
│
├── scripts/                        # Development and verification scripts
├── data/                           # Local runtime data (uploaded files, indices, etc.)
├── private/                        # Non-standard deliverables (exam questions, emails, etc.)
└── tmp/                            # Rendered output, debug logs, and temporary files
```

## Current backend smoke check

Install `backend/requirements.lock.txt` in the project Python 3.12 environment,
then run from the repository root:

```powershell
& ./backend/.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000
```

Open `/api/health` on that local server. No model keys are required. Startup
creates/checks the configured local runtime directory and SQLite file; health
success is not an upload/question-answering acceptance result. See the development
setup for configuration precedence, startup failures and current validation.

## Docker startup

Use the startup sequence in **Ask questions with Docker** above, including the
one-off tokenizer preparation for PDF indexing. Startup, health checks and CSV
processing do not require provider keys; answering questions requires generation
credentials, and PDF indexing/retrieval also requires Voyage credentials.

Optional verification and lifecycle commands (use your configured ports):

```powershell
docker build --target test -t siteco-backend:test -f backend/Dockerfile .
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/api/health # Replace 8000 with your configured HOST_PORT
docker compose logs frontend backend
docker compose stop
docker compose start --wait --wait-timeout 60
docker compose down
```

Open **http://127.0.0.1:8080** for the document workspace. Expect two healthy
services, and `status=ok`, `version=0.1.0` from `/api/health` through either port.
For startup failures, run `docker compose logs frontend backend`. The explicit
test-target build above runs the Linux tests; Compose
builds the runtime target without test dependencies. Initial builds need internet
to download the base image and packages; health/startup do not call models.

By default, Compose binds `./data/runtime` to `/app/runtime`; `down` removes the container
and network while leaving that host directory intact. A later `up --wait`
reuses it. The frontend serves static assets and proxies `/api` to the backend;
it receives no provider keys or runtime-data mount. Set `FRONTEND_PORT` to
override its loopback host port (default 8080). The backend listens on container port 8000, published only on
`127.0.0.1:8000`. Set `HOST_PORT` to change the host port and `HOST_DATA_DIR` to
change the host directory (Windows example: `D:/siteco-runtime`). Relative mount
paths resolve from the Compose project directory. Container DATA_DIR and APP_PORT
are fixed by Compose; the corresponding `.env` values are for local Python runs.

Optional configuration: copy `.env.example` to root `.env` without overwriting an
existing file, then fill only the values needed. Shell variables take precedence.
Compose explicitly passes the listed provider/model/key variables at runtime;
it does not copy `.env` or read the three local key text files. Keys never enter
build arguments. Do not share expanded `docker compose config` or container env
output when using real credentials; `docker compose config --quiet` validates
without displaying values. Changing runtime variables requires `up -d` to
recreate the container, not just `restart`.

Backend configuration defaults are `GENERATION_PROVIDER=gemini`,
`GEMINI_GENERATION_MODEL=gemini-3.5-flash-lite`,
`GROQ_GENERATION_MODEL=openai/gpt-oss-120b`, `EMBEDDING_PROVIDER=voyage`,
and `EMBEDDING_MODEL=voyage-4`. Gemini uses `GEMINI_API_KEY`; explicitly selecting
Groq uses `GROQ_API_KEY`. Generation model names are configurable, but this does
not establish compatibility or quality for every model. The recorded real M3
checks used Gemini, not a multi-provider comparison. PDF indexing supports the
pinned Voyage model/tokenizer; arbitrary embedding models, base URLs and
in-browser key management are not supported. See [.env.example](.env.example)
and [development notes](docs/development.md).

### Enable PDF indexing

Set `VOYAGE_API_KEY` only for the backend. Keep `EMBEDDING_MODEL=voyage-4`.
Prepare the pinned tokenizer JSON once through the backend image before uploading
PDFs (it writes to the same HOST_DATA_DIR bind mount):

```powershell
docker compose run --rm --no-deps backend python -m app.prepare_tokenizer /app/runtime/tokenizers
```

Keep `/app/runtime/tokenizers` as the container destination. Set `HOST_DATA_DIR`
to choose the host bind-mount directory; the resulting host file is
`HOST_DATA_DIR/tokenizers/voyage-4-tokenizer.json`. This is tokenizer
data, not model weights; startup never downloads it. Keys, tokenizer and runtime files are not
baked into images. Recreate the backend after changing its configuration.

Missing keys leave PDF parsing explicitly failed with `retrieval_not_configured`;
missing/invalid tokenizer or another model yields `embedding_configuration_invalid`.
Fix configuration and upload again for these non-retryable configuration states.
Published PDFs restore from local artifacts without embedding calls. New queries
require query embeddings, unless already cached; retrieval requires configured
Voyage/tokenizer even when the query is cached. The single shared budget is
configurable through `EMBEDDING_RPM`, `EMBEDDING_TPM`, and `EMBEDDING_MIN_INTERVAL`: defaults are 3 RPM/10K TPM and 20 seconds between starts. The current local demonstration uses 60 RPM/200K TPM and 1 second, with a 1-second rerank interval; these are local admission limits, not verified account allowances. Waiting is visible
during ingestion; no paid-plan switch is automatic.

## Using the workspace

- Choose PDF/CSV files or drag files onto the page. Use Attach → Choose folder
  to review supported files before uploading; unsupported/empty/oversized files
  are listed as skipped. Folder selection depends on browser support; ordinary
  multi-file selection remains available. Folder drag-and-drop is not supported.
- Uploads are sent individually. Received means queued, not ready. Do not
  automatically repeat an upload after a network interruption: refresh the
  material list first, because the server may already have received it.
- Open Materials for states, extraction coverage, warnings and eligible retries.
  Only ready documents can be selected or have extracted evidence previewed.
  Selection survives refresh in the same tab and is rechecked for readiness; a new
  conversation clears it. Uploaded files remain on the server. Coverage is not accuracy.
- Session info describes temporary memory. Settings configures supported model providers, in-memory keys and retrieval parameters. Long-term conversations and cross-conversation history are not implemented. Temporary multi-turn answers are supported as described below.

## Original source previews

Expand an answer citation and choose **Open original source**. PDF previews display
its original physical page, with solid amber evidence regions and dashed blue
context/headings. Zoom and Fit page move the image and overlays together. This is
source-region highlighting, not word-by-word semantic verification. CSV previews
show the cited logical record and every original field, including empty values;
current citations do not identify which individual fields support a sentence.

Previews resolve the document/evidence IDs again each time they are opened. Unknown
or unavailable sources show an error while the saved citation text remains readable.
Missing/unreliable coordinates show the page with a positioning notice and no boxes.
PDF images are rendered locally at up to 144 dpi, capped at 1,600 pixels on the long
edge; zoom does not create additional detail. Rendering uses the existing locked
PDF dependencies, with no model calls or external viewer. Original file downloads
and arbitrary filesystem paths are not exposed. See the [preview contract](docs/m43-preview-contract.md).

## Frontend development and browser checks

With Node.js 24 and the backend listening on `127.0.0.1:8000`:

```powershell
npm ci --prefix frontend --ignore-scripts
npm run dev --prefix frontend
npm run build --prefix frontend
```

Open `http://127.0.0.1:5173`; Vite proxies `/api` to the backend. Build performs
TypeScript checks before generating static assets. Docker uses the same npm lock.
See [M2.4 browser checks](docs/development.md#m24-frontend-and-browser-checks)
for isolated acceptance commands; tests do not call model providers.

## Upload reception (M2.2.1–2)

With the backend running, submit one PDF or CSV per request:

```powershell
curl.exe -F "file=@C:/path/to/sample.csv" http://127.0.0.1:8000/api/documents
```

Success returns HTTP 202 with `document_id`, `original_filename`, and
`status: queued`. Every upload receives its own ID, including identical names
and content. Files are stored under runtime/uploads using server-generated IDs;
metadata is in app.sqlite3. Reception does not require a model key.

Limits: 20 MiB actual file bytes, at most 10 occupied document slots including
uploads being received. Rejected uploads release their reservation. Only one
`file` multipart field is accepted; transport overhead is bounded to 64 KiB
above the file limit. PDF headers are checked, while full PDF validity, page
count are checked asynchronously by the PDF parser (maximum 50 pages). CSV uses
the fixed UTF-8/semicolon/18-column price-list schema, with a 20,000 logical-record
limit; structural errors fail the whole file. Errors include 413 (size),
415 (type), 409 (capacity), 422 (empty/malformed request), and sanitized 503
(storage unavailable), with `error.code/message/retryable`.

The backend accepts uploads as queued, then its single background
worker parses PDFs and persists evidence, page coverage and warnings. With PDF
configuration present it embeds the evidence and publishes vectors, source
mapping and FTS together before ready. CSV becomes ready only after all records and the
exact SQLite index are persisted and validated. Missing/invalid prices retain
their original values and warnings; they never become numeric zero. A file with
no searchable order IDs fails explicitly. Status, retry and evidence endpoints are available below.

The lifecycle supports queued → processing → ready/failed, whole-document
publication, and explicit manual retry of retryable failures using the same ID.
On shutdown/restart, unfinished jobs become `processing_interrupted`; they are
not automatically resumed. Ready artifacts are restored before queries become
available; restoration failure is explicit. CSV and PDF/FAISS restoration have
been accepted; corrupt PDF artifacts fail closed and can be retried.

Execution is one process, one bounded in-memory queue and one worker thread.
Shutdown requests cooperative cancellation and waits up to two seconds; late
results cannot publish. Provider calls use finite timeouts and honor
cancellation. This is not a durable task queue or an exactly-once guarantee.

## Document status and evidence

- `GET /api/documents`: array of documents, ordered by creation time and ID.
- `GET /api/documents/{id}`: current status, stage and structured error.
- `POST /api/documents/{id}/retry`: 202 for eligible failed documents; 409 for
  non-retryable/active documents or a full workspace. The ID stays the same.
- `GET /api/documents/{id}/evidence?offset=0&limit=20`: array of evidence, only
  available when ready; 409 otherwise. Limit is 1–100; offset is non-negative.

Unknown IDs return 404. Errors use `error.code/message/retryable`; invalid query
parameters return a sanitized 422. Responses exclude stored paths and config.
Metadata includes file type, size and timestamps. `progress` is null until actual
counts are available. PDF `parsing` includes parser_version, page_count, coverage,
evidence_count and coverage_limited; `warnings` includes physical page numbers,
fixed codes and explanations. Both persist across restart. Before parsing the
summary is null; unreadable/over-limit PDFs have an unknown (null) page_count,
not a fabricated count. coverage_limited=false does not prove complete extraction.
No invented percentages or
completion estimates are shown. Poll about once per second while queued/processing
and stop when ready/failed; this is a client recommendation, not server push.

CSV `parsing` uses `kind: csv`, `record_count`, `indexed_record_count` and
`price_counts`, with record/column warnings instead of PDF pages. Evidence
preserves ordered headers, raw string values and logical record numbers. A valid
normalized price is a decimal string; missing/invalid prices are null.
`DocumentService.lookup_orders(order_ids, document_ids, offset=0, limit=50)` is
the deterministic backend entry: explicit ready CSV scope, exact case-sensitive
keys, all duplicate sources, full counts and pagination. The production question
task API calls this method through validated planning; completed tasks expose
CSV pagination through their frozen scope (see the [question API contract](docs/m28-chat-contract.md)).

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/documents
Invoke-RestMethod http://127.0.0.1:8000/api/documents/REPLACE_WITH_DOCUMENT_ID
```

M2.2 acceptance covers upload identity/limits, lifecycle, publication gates,
interruption and the HTTP contract. Controlled processors prove successful
publication in tests. M2.3 accepts PDF-to-evidence and durable coverage; M2.5
accepts real CSV document-to-ready and exact lookup. M2.6 accepts configured PDF
publication, scoped hybrid retrieval and restoration. M2.7 adds evidence-based
answers and validated citations; M2.8 verifies fresh PDF/CSV uploads through the
Docker browser chat and source display (see [acceptance](eval/results/m28_chat.md)).
Use HTTP to read live state; do not open the
running container's SQLite database from Windows.

## Temporary conversation memory (M3)

Follow-up submissions may include `previous_question_id` referring to a completed
question in the same conversation. The browser attaches the most recent completed
turn and preserves that link when recovering an ambiguous submission. Refresh uses
GET polling and does not automatically POST questions again.

The backend resolves subjects from at most 6 recent whole turns (12,000 serialized
characters total), then retrieves evidence only from the current selected documents.
Previously validated subjects are retained as identity clues within that same budget.
For a previously resolved turn, a phrase found only in its original question cannot
authorize another lookup; references must match a retained subject or source text.
History is not evidence for the new answer. Missing or ambiguous references require
clarification. The extra structured model call shares the original 240-second budget.
Model reference selection can still be wrong; inspect the displayed resolved subjects
and current citations. Reference identity validation does not prove semantic accuracy.

Retention ends 24 hours after the conversation's first question, without renewal by
follow-ups. The API returns `conversation_expires_at`; expired conversations require
an explicit new conversation. Completed history survives backend restarts during
retention; unfinished tasks remain interrupted and are never automatically replayed.
There is no cross-conversation memory, long-term history, or authentication.
See [the memory contract](docs/m3-memory-contract.md) for bounds and verification.

## Current limitations

PDF support covers text-based documents up to 50 pages; extraction warnings and
missing layout relationships can limit answers. OCR, visual/checkmark interpretation
and semantic verification of generated prose are absent.
CSV support is limited to the documented price-list schema, not arbitrary spreadsheets.
A provider failure in a required route fails the question; it is not silently
presented as an incomplete successful answer. Questions use one worker with up to
8 waiting tasks and 1,000 retained task records; the browser permits up to 50 turns
per conversation. There is no streaming, cancellation API, durable job queue,
authentication or long-term/cross-conversation memory. Small real checks do not
establish a general accuracy rate or stable latency percentile.

M4.2 targeted repairs and verification are recorded in [the development checkpoint](eval/results/m42_experience.md).
These sampled checks are not a formal benchmark or a general reliability estimate.


## Runtime Settings

Open Settings to choose Gemini/Groq, set the model and Key, change PDF Top K (1–20), or enable reranking. Voyage remains voyage-4 with the existing index format; alternate embedding endpoints and index rebuilding are outside scope. Candidate counts and the context budget remain fixed; per-turn diagnostics distinguish selected sources from sources included in context.

Apply saves instance-wide overrides in backend memory without contacting providers. Refresh preserves applied configuration; backend restart restores startup environment defaults. Blank Key fields keep the existing value. Clear credentials disables new tasks; Restore defaults may re-enable startup credentials. Already accepted questions and uploads retain their frozen configuration. Keys are never returned to the browser or persisted by Settings.

Connection tests explicitly send fixed text to the selected provider and may incur charges. Apply a draft before testing it. A passing simple structured-output probe does not guarantee full question capability; service health alone does not validate a Key. This remains a local single-user application without multi-user authentication.


### Verified configuration path and account limits

1. Start the application with Docker as described above; open Settings.
2. Select Gemini or Groq, enter a model supported by your account and its API Key. The tested models are `gemini-3.5-flash-lite` and `openai/gpt-oss-120b`, respectively. Groq models must support the strict JSON-schema mode used by this application; see [Groq structured-output support](https://console.groq.com/docs/structured-outputs). Arbitrary model names are not guaranteed to work.
3. Enter a Voyage API Key with access to `voyage-4`, then Apply settings. Use Test inference & JSON and Test embedding for fixed-text checks; a simple probe does not verify the full question schema or your document-size allowance.
4. Upload a small PDF, wait for Ready, select it, and ask a factual question. Expand its citation and Open original source to check the physical page and evidence region.
5. If the provider rejects request size, lower PDF Top K in Settings and/or select fewer materials, then explicitly submit a new question. There is no automatic truncation, retry or paid-tier change. A smaller Top K may omit evidence required for broader questions.

Live development acceptance used a six-page business-partner code of conduct. Gemini passed at Top K 8. This Groq account rejected the full request at Top K 8 (8,000 TPM allowance versus 9,097 requested), then passed at Top K 1. These are observed account-specific results, not universal limits or a guarantee that Top K 1 fits every document. Both answers were checked against the original page and highlighting. See [acceptance evidence](eval/results/m45_live_settings.json), including the original failure. Clean-runtime delivery reproduction remains an M5 check.
