# SITECO Document Retriever

M0 development foundation is complete. The repository currently contains three standalone migrated modules (rank fusion, lexical retrieval, and tracing) and 10 tracing tests. M2.1.1 adds a validated configuration loader with optional credentials and project-root dotenv resolution. M2.1.2 adds a minimal FastAPI health endpoint and local storage startup checks. M2.1.3–4 verify the shared dependency locks on Windows and Linux and provide a tested backend Docker image. M2.1.5–6 add verified Compose startup and persistent host storage. M2.2.1–2 add persistent upload reception. M2.2.3–4 add the lifecycle and background worker. Actual parsing/indexing, question answering and frontend are not implemented yet.

See [development setup](docs/development.md) for Python 3.12 environment creation, pinned dependency installation, and verification commands. See [reuse notes](docs/reuse.md) for provenance and migration boundaries.

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

## Backend Docker startup (M2.1)

Run from the repository root with Docker Desktop using Linux containers. No host
Python or model keys are needed. Stop any local server using port 8000 first.

```powershell
docker build --target test -t siteco-backend:m21-test -f backend/Dockerfile .
docker compose up --build --wait --wait-timeout 45
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/api/health
docker compose stop
docker compose start --wait --wait-timeout 45
Invoke-RestMethod http://127.0.0.1:8000/api/health
docker compose down
```

Expect `status=ok`, `version=0.1.0` and a healthy backend. For startup failures,
run `docker compose logs backend`. The first build runs the Linux tests; Compose
builds the runtime target without test dependencies. Initial builds need internet
to download the base image and packages; health/startup do not call models.

Compose binds `./data/runtime` to `/app/runtime`; `down` removes the container
and network while leaving that host directory intact. A later `up --wait`
reuses it. The backend listens on container port 8000, published only on
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

M2.1 is validated for basic startup and disk persistence only. Final delivery
remains separate frontend and backend containers; currently only the backend
service exists. Upload reception is available; processing and question answering are not yet available.
See [development notes](docs/development.md) for acceptance evidence and limits.

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
count, CSV structure and record count await parsing. Errors include 413 (size),
415 (type), 409 (capacity), 422 (empty/malformed request), and sanitized 503
(storage unavailable), with `error.code/message/retryable`.

This intermediate build accepts uploads as queued, then its single background
worker reports `failed` with `processing_not_configured`: real parsing/indexing
is not connected yet. No fake successful processing is used. Status, retry and evidence HTTP endpoints are available as described below.

The lifecycle supports queued → processing → ready/failed, whole-document
publication, and explicit manual retry of retryable failures using the same ID.
On shutdown/restart, unfinished jobs become `processing_interrupted`; they are
not automatically resumed. Ready artifacts are restored before queries become
available; restoration failure is explicit. These success paths are verified
with controlled test processors, not real PDF/CSV or FAISS acceptance.

Execution is one process, one bounded in-memory queue and one worker thread.
Shutdown requests cooperative cancellation and waits up to two seconds; late
results cannot publish. Future provider calls must use finite timeouts and honor
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
counts are available; `warnings` is currently empty. No invented percentages or
completion estimates are shown. Poll about once per second while queued/processing
and stop when ready/failed; this is a client recommendation, not server push.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/documents
Invoke-RestMethod http://127.0.0.1:8000/api/documents/REPLACE_WITH_DOCUMENT_ID
```

M2.2 acceptance covers upload identity/limits, lifecycle, publication gates,
interruption and the HTTP contract. Controlled processors prove successful
publication in tests. Production still reports processing_not_configured until
real parsing/embedding/indexing is integrated; real document-to-ready and question
answering acceptance remain pending. Use HTTP to read live state; do not open the
running container's SQLite database from Windows.
