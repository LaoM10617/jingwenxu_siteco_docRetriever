# SITECO Document Retriever

The current M2.6 build provides a React/TypeScript document workspace and a FastAPI backend, started together with Docker Compose. Upload PDF/CSV files, inspect processing states and extraction warnings, and restore the material list after refresh. Supported price-list CSVs provide exact backend order lookup. Configured PDFs provide SQLite FTS5/BM25 and Voyage/FAISS retrieval with RRF fusion, after complete publication. Chat answers remain pending; the chat composer is disabled.

See [development setup](docs/development.md) for Python 3.12 environment creation, pinned dependency installation, and verification commands. See [reuse notes](docs/reuse.md) for provenance and migration boundaries.

M2.6 connects a shared quota/cache gateway, per-document FAISS IndexFlatIP,
atomic PDF publication and scoped hybrid retrieval. See the
[retrieval contract](docs/m26-retrieval-contract.md) and
[Docker retrieval acceptance](eval/results/m26_hybrid.md). Retrieval is a backend
method; there is no production query HTTP endpoint before the M2.7 chat layer.

## Planned directory structure

Empty directories are not tracked by Git. Requirements, private materials, runtime data, and temporary files below are local-only.

```text
Retrieval_SITECO/
├── README.md                      # Entry point for operators and reviewers
├── AGENTS.md                      # Project collaboration rules
├── requirements_draft.md           # Requirements, scope of support, and items for discussion
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

Run from the repository root with Docker Desktop using Linux containers. No host
Python, Node.js or model keys are needed for startup or CSV processing. PDF
indexing requires the configuration below. Stop any local server using ports 8000 or 8080 first.

```powershell
docker build --target test -t siteco-backend:test -f backend/Dockerfile .
docker compose up --build --wait --wait-timeout 45
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/api/health
docker compose stop
docker compose start --wait --wait-timeout 45
Invoke-RestMethod http://127.0.0.1:8000/api/health
docker compose down
```

Open **http://127.0.0.1:8080** for the document workspace. Expect two healthy
services, and `status=ok`, `version=0.1.0` from `/api/health` through either port.
For startup failures, run `docker compose logs frontend backend`. The explicit
test-target build above runs the Linux tests; Compose
builds the runtime target without test dependencies. Initial builds need internet
to download the base image and packages; health/startup do not call models.

Compose binds `./data/runtime` to `/app/runtime`; `down` removes the container
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

M2.4 validates the upload/status workspace and two-container proxy. M2.5 adds
real CSV upload-to-ready, evidence pagination, exact order lookup and restoration
after container recreation. M2.6 adds PDF ready publication and backend hybrid
retrieval; question answering remains pending.
See [CSV contract](docs/m25-csv-contract.md) and [acceptance](eval/results/m25_csv.md).
See [development notes](docs/development.md) for acceptance evidence and limits.

### Enable PDF indexing

Set `VOYAGE_API_KEY` only for the backend. Keep `EMBEDDING_MODEL=voyage-4`.
Prepare the pinned tokenizer JSON once in the host runtime directory before
uploading PDFs (use the same directory as `HOST_DATA_DIR`):

```powershell
& ./backend/.venv/Scripts/python.exe scripts/prepare_voyage_tokenizer.py D:/Projects/Retrieval_SITECO/data/runtime/tokenizers
```

Replace the example destination with your actual `HOST_DATA_DIR/tokenizers/`.
The script places `voyage-4-tokenizer.json` there. This is tokenizer
data, not model weights; startup never downloads it. Keys, tokenizer and runtime files are not
baked into images. Recreate the backend after changing its configuration.

Missing keys leave PDF parsing explicitly failed with `retrieval_not_configured`;
missing/invalid tokenizer or another model yields `embedding_configuration_invalid`.
Fix configuration and upload again for these non-retryable configuration states.
Published PDFs restore from local artifacts without embedding calls. New queries
require query embeddings, unless already cached; retrieval requires configured
Voyage/tokenizer even when the query is cached. The single shared budget is
3 RPM/10K TPM with at least 20 seconds between request starts. Waiting is visible
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
  Only ready documents can be selected or previewed. The selection lasts for the
  current page; uploaded files remain on the server. Coverage is not accuracy.
- History and Settings explain their current limitations. Persistent conversations,
  personal API key controls, multi-turn answers and original-page highlighting
  are not implemented in this build.

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

This intermediate build accepts uploads as queued, then its single background
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

## Document status and evidence (M2.2 accepted)

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
keys, all duplicate sources, full counts and pagination. There is no production
query HTTP route yet; the later chat layer will call this method.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/documents
Invoke-RestMethod http://127.0.0.1:8000/api/documents/REPLACE_WITH_DOCUMENT_ID
```

M2.2 acceptance covers upload identity/limits, lifecycle, publication gates,
interruption and the HTTP contract. Controlled processors prove successful
publication in tests. M2.3 accepts PDF-to-evidence and durable coverage; M2.5
accepts real CSV document-to-ready and exact lookup. M2.6 accepts configured PDF
publication, scoped hybrid retrieval and restoration; question answering remains pending.
Use HTTP to read live state; do not open the
running container's SQLite database from Windows.
