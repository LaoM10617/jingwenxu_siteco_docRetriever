# Development setup

## M2.4 frontend and browser checks

The frontend is React 19.3.0, TypeScript 7.0.2, Vite 8.3.1 and plugin-react
6.1.1, with exact direct versions and `frontend/package-lock.json`. Windows
Node 24.19.0/npm 11.17.0 and the pinned Linux Node 24.21.0 image built the same
lock successfully. The static runtime is nginx 1.30.5; both new base images are
pinned by digest in `frontend/Dockerfile`. Vite guidance:
https://vite.dev/guide/ . Registry versions were checked before installation.

Start an isolated pair for browser acceptance (PowerShell, repository root):

```powershell
$env:HOST_PORT = '18086'
$env:FRONTEND_PORT = '18087'
$env:HOST_DATA_DIR = 'D:/Projects/Retrieval_SITECO/tmp/m24-acceptance/runtime'
docker compose --env-file .env.example -p siteco-m24-acceptance up --build --wait
npm ci --prefix frontend --ignore-scripts
$env:M24_BASE_URL = 'http://127.0.0.1:18087'
$env:M24_PDF = 'D:/Projects/Retrieval_SITECO/data/Brochures/Indoor Lightening/SITECO_Rondel_21_Product_Flyer.pdf'
$env:M24_REAL_PROXY = '1'
npm test --prefix frontend
```

Adapt the two absolute D-drive paths on another machine. Use only an existing
development PDF, not held-out material. The real-upload test submits the PDF
twice and leaves independent failed records/files in this isolated runtime.
It checks receipt, parsing, not-ready evidence access, refresh without resubmission
and distinct IDs. It expects the current intermediate `retrieval_not_configured`
result; update this acceptance when real indexing is implemented.

Playwright 1.63.0 uses installed Microsoft Edge (`msedge`) by default; no browser
download was needed here. Set `PLAYWRIGHT_CHANNEL` for another installed channel.
Without `M24_PDF`, the real PDF test is explicitly skipped. Without
`M24_REAL_PROXY=1`, the live proxy-limit test is explicitly skipped. Other tests
use controlled responses at the existing HTTP seam, not production ready data.

Checks: ready selection by ID; waiting quota; retryability; evidence pagination;
409 preview rejection; network recovery; directory review/unsupported files;
drag upload; explicit server rejection without automatic POST retry; polling to
terminal status while keeping ready selection; mobile Escape/focus behavior.
Actual proxy checks cover `/api/health`, 404, 415 and the backend's 20 MiB limit
through nginx. Its 21 MiB request cap allows multipart overhead; backend limits
remain authoritative. No model calls are made.

Verified separately: Vite on 5173 proxied health to a real backend on 8000;
replacing only the backend container preserved list/detail metadata and warnings,
and the still-running nginx resolved the replacement via Docker DNS. All live
state inspection used HTTP, never a Windows connection to running SQLite.

Stop this isolated preview when no longer needed:

```powershell
docker compose --env-file .env.example -p siteco-m24-acceptance down
```

The data directory stays intact. Unset the temporary `HOST_PORT`,
`FRONTEND_PORT`, `HOST_DATA_DIR` variables before starting the normal workspace.
Screenshots and test artifacts are ignored. M2.4 proves upload/status and
two-container integration, not real retrieval, answers or complete M2 acceptance.

M0 provides three standalone migrated modules, one tracing test file, and a
minimal Python dependency set. It is not a running document-chat application.

## Verified environment (2026-09-26)

- Windows x64, independent Python 3.12.10, pip 25.0.1.
- rank-bm25 0.2.2 and its NumPy 2.5.3 dependency.
- Node.js 24.19.0 and npm 11.17.0.
- Docker Desktop 4.92.0, Engine/CLI 29.8.0, Compose v5.5.1.
- WSL 2.7.14.0, docker-desktop distribution using WSL 2, Linux/amd64 containers.

Python 3.12 is the confirmed project version. Other versions identify the tested
setup. M2.1.3–4 also verified Debian 12 (bookworm), Linux/amd64, Python 3.12.14 and the backend image.

## Checkout

Access to the private repository is required:

```powershell
git clone https://github.com/LaoM10617/jingwenxu_siteco_docRetriever.git
cd jingwenxu_siteco_docRetriever
```

Run subsequent commands from the repository root. Empty directories shown in the
planned README structure are not tracked by Git and can be created when needed.

## Independent Python installation

Use an independent 64-bit Python 3.12 installation, not a copied virtual environment
or a Codex cache. This machine uses the signed Python Software Foundation
[3.12.10 Windows installer](https://www.python.org/downloads/release/python-31210/),
installed for the current user in `%LOCALAPPDATA%/Programs/Python/Python312`.
Its Authenticode signature was validated before installation.

3.12.10 is the last release with traditional Windows installers, not the latest
security patch. [3.12.14](https://www.python.org/downloads/release/python-31214/)
is newer. The local patch version does not require the delivered container to use
an older patch; select and validate the container runtime separately.

The installer options used were:

```text
/quiet InstallAllUsers=0 TargetDir="<LOCALAPPDATA>/Programs/Python/Python312" PrependPath=0 AssociateFiles=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_pip=1 Shortcuts=0
```

Replace `<LOCALAPPDATA>` with the user installation directory. These options keep
an existing Python launcher, PATH and file associations. On a fresh machine,
include the launcher or use the interpreter's full path. Global `python` remains
3.14.7 on this machine; explicitly select 3.12 for the project.

## Create the environment and install dependencies

```powershell
py -3.12 --version
py -3.12 -c "import sys; print(sys.executable)"
py -3.12 -m venv backend/.venv
& ./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
& ./backend/.venv/Scripts/python.exe -m pip check
& ./backend/.venv/Scripts/python.exe -c "import sys; assert sys.version_info[:2] == (3, 12); assert sys.prefix != sys.base_prefix; print('Base:', sys.base_prefix)"
```

The base must be the independent Python installation. Activation is optional.
`backend/requirements.txt` declares direct dependencies; the lock file pins the
runtime and transitive packages validated on Windows x64 / Python 3.12.10 and Linux/amd64 / Python 3.12.14.
Do not install the old project's full dependency list.

To rebuild, stop processes using this project's environment, verify the absolute
path is this checkout's `backend/.venv`, remove only that directory, and repeat
the commands above. Do not modify `pyvenv.cfg` to switch interpreters. The venv is
ignored by Git and depends on the independent base installation.

## Check the migrated modules

```powershell
& ./backend/.venv/Scripts/python.exe -B tests/test_tracing.py
& ./backend/.venv/Scripts/python.exe -B -c "import sys; sys.path.insert(0, 'backend'); from app.retrieval.fusion import reciprocal_rank_fusion; assert reciprocal_rank_fusion([['a','b'],['b','c']]) == ['b','a','c']; print('Fusion smoke check passed')"
& ./backend/.venv/Scripts/python.exe -B -c "import sys; sys.path.insert(0, 'backend'); from app.retrieval.lexical import BM25Index; i=BM25Index(); i.replace_documents([('a','LED-100 Leuchte')]); assert i.search('LED-100',5)==['a']; i.replace_documents([('a','Leuchte'),('b','Sensor')]); assert i.search('Sensor',5)==['b']; assert i.search('unknown',5)==[]; print('Lexical smoke check passed')"
```

The tracing file contains 10 unittest cases. Fusion/lexical formal tests are
explicitly deferred until subsequent implementation. Their smoke checks do not
establish retrieval quality, document-scope integration or end-to-end behavior.
Callers must filter document scope before the final top_k selection.

## Docker and WSL 2

Start Docker Desktop and wait for its Linux engine, then run:

```powershell
wsl --version
wsl --list --verbose
docker version
docker compose version
docker info --format '{{.OSType}} {{.Architecture}} {{.KernelVersion}}'
docker run --rm hello-world
```

Earlier environment verification passed: Client and Server available, Linux
containers, WSL 2 and `Hello from Docker!`. The command may download the test
image; the container is removed on exit and the image remains cached.

The current Codex process may have an older PATH than the saved user PATH. For
this per-user installation, a validated session-only fallback is:

```powershell
$dockerBin = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin'
$env:Path = "$dockerBin;$env:Path"
docker version
```

Alternatively, restart the terminal's parent application. No permanent PATH or
WSL changes are required. Ubuntu integration is not needed for PowerShell use.

## Node.js and npm

```powershell
node --version
npm --version
node -e "const assert=require('node:assert/strict'); assert.equal(JSON.parse(JSON.stringify({ok:true})).ok,true); console.log('Node runtime check passed')"
```

These passed during environment setup. No frontend package manifest exists yet;
no frontend install or build has been performed. Add the manifest and lockfile
when the frontend is selected.

## Remaining integration work

- FastAPI/configuration and the backend Linux image are implemented; parsers, model SDKs and frontend dependencies arrive with their respective features.
- The backend-only Docker build allowlist excludes local data, credentials, environments and Git. Extend it deliberately when the frontend gets its own build.
- Compose and host data mounts are verified below. Frontend, upload-to-answer flow and fusion/lexical formal suites remain pending.

## M2.1.1 configuration entry point

Implemented in `backend/app/config.py`; this step does not start an HTTP server.
Install runtime dependencies using `backend/requirements.lock.txt`, or include
tests with:

```powershell
& ./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.lock.txt
& ./backend/.venv/Scripts/python.exe -m pytest -q
```

Applications call `load_settings()` during startup, not at module import. It
loads process environment variables before the project-root `.env`, then uses
defaults. The optional root `.env` is located from the module's project layout,
not the current working directory. Copy `.env.example` to `.env` if needed; never
overwrite an existing `.env` without preserving its values. Key text files are
not read automatically. No real `.env` was generated during this step.

`load_settings(env_file=Path(...))` selects a different dotenv file; relative
file paths resolve against the project root, and custom files must exist.
`load_settings(env_file=None)` disables dotenv loading but still reads environment
variables. Relative `DATA_DIR` paths also resolve against the project root.
A missing default `.env` is permitted; a directory supplied as `.env` is rejected.
The later Docker layout must preserve `backend/app` under the application root
and will set an absolute `DATA_DIR=/app/runtime`.

`APP_PORT` defaults to 8000 and must be an integer in 1..65535. `DATA_DIR` defaults
to `data/runtime`; blank paths and paths conflicting with existing files fail.
Directories are not created here. Actual write permissions and SQLite access
will be verified by the application startup step (M2.1.2).

Gemini, Groq and Voyage keys may be absent or blank. They are stored as SecretStr,
omitted from the settings repr, and redacted in JSON serialization. Provider and
model configuration follows `.env.example`. Loading configuration does not
validate credentials remotely, instantiate SDK clients, or access the key text
files. Callers display `ConfigurationError` with field-level reasons and never
log a complete settings object or call `get_secret_value()` for diagnostics.
This protects ordinary error/traceback output, not debuggers configured to dump
all local variables.

Validation: 16 configuration tests plus 10 existing tracing tests passed on
Windows/Python 3.12.10; `pip check` and a dry-run installation from the development
lock passed. New runtime pins are pydantic-settings 2.15.0 and pydantic 2.13.5;
pytest 9.1.1 is test-only. Linux installation and container startup remain
unverified until the following M2.1 steps.

## M2.1.2 minimal API and startup checks

Start from the repository root:

```powershell
& ./backend/.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000
```

Uvicorn's CLI owns the listening address/port; `--port` must be set explicitly
when using a non-default port (`APP_PORT` is validated application configuration,
not an automatically consumed Uvicorn CLI variable). Use a matching value for
both until the container launch configuration is added. Stop with Ctrl+C.

`GET http://127.0.0.1:8000/api/health` returns HTTP 200 and
`{"status":"ok","version":"0.1.0"}`. This is the initial application version,
not a Git commit or a claim of feature completeness. No upload endpoint exists.

`create_app(settings=None)` loads configuration when called; module import does
not initialize storage. FastAPI lifespan creates DATA_DIR and checks writing
with a temporary file, then opens `app.sqlite3` and performs a short SQLite write
transaction that is rolled back. Connections and temporary files are closed.
Existing database records and user_version are preserved; no business tables
are created. A missing database can be created by this check. Permission,
invalid-database or lock errors stop startup with a sanitized StartupError.
The one-second SQLite lock timeout makes startup fail promptly if another writer
is holding the database. This is not a corruption repair or migration mechanism.

Health checks do not call providers or continuously re-test storage; success
means the app completed its local startup checks and serves requests. It does
not prove available model quota, retrieval quality or working uploads.

Validation: 6 API/startup tests, 16 configuration tests and 10 tracing tests
passed (32 total; plus 10 unittest subtests). A real short-lived Uvicorn process
returned the expected health response using empty keys and an isolated ignored
`tmp/` runtime directory, then was stopped. `pip check` and development-lock
installation dry-run passed. Starlette 1.7.0 currently emits one deprecation
warning for its httpx TestClient compatibility path; tests still pass. We have
not changed test clients or suppressed the warning. Linux/Docker remains pending.

## M2.1.3–4 shared locks and Linux backend image

`backend/requirements.txt` declares runtime dependencies; `requirements.lock.txt`
pins their transitive versions. The corresponding `requirements-dev` files add
test dependencies. Both platforms use the same locks; Colorama has an explicit
Windows-only marker. No parsers, model SDKs or frontend dependencies were added.

The Dockerfile pins the official `python:3.12-slim-bookworm` base to:

```text
sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
```

Actual runtime: Python 3.12.14, Debian GNU/Linux 12, x86_64. Only Linux/amd64 was
verified. Refresh the digest deliberately when updating the base and rerun checks.
Build/run commands are in README; use the repository root as the build context.
The `test` target installs development dependencies and runs tests as UID 10001.
The final `runtime` target excludes those dependencies and test files. It runs
one Uvicorn worker as UID/GID 10001, without reload, on port 8000. Host mapping
can change independently; APP_PORT does not override the image's explicit CLI
port or healthcheck. DATA_DIR defaults to `/app/runtime` inside the image.

Validation on 2026-09-26: installation and pip check passed on both platforms;
32 tests plus 10 subtests passed on each. The existing Starlette/httpx deprecation
warning remains visible. Runtime imports passed; pytest/httpx are absent from
the runtime image. A real temporary container without keys returned HTTP 200
with status/version, became Docker-healthy, and opened SQLite as UID 10001.
It was stopped and removed after verification. No provider calls were made.

The runtime image reports 302,856,531 bytes of logical image size. Docker system
df reports shared image storage separately from build cache (444 MB images and
300.8 MB cache after this run); these figures are not additive physical VHDX usage.
C: had about 27.7 GiB free afterward. Docker storage remains on C:, while the
planned host runtime mount remains on D:. No unrelated Docker data was cleaned.
Container rebuild persistence and host mount permissions are not yet verified;
M2.1.5 will add Compose and verify the actual bind mount. No frontend is bundled.

## M2.1.5–6 Compose and acceptance

Use the README commands for build, startup, health, stop/start and teardown.
`compose.yaml` supplies an explicit runtime environment allowlist, an IPv4
loopback host port, and a configurable bind source. The image provides the
healthcheck and fixed non-root user. No automatic restart policy is used, so a
configuration/startup error stays visible instead of looping. On native Linux,
the host directory must be writable by UID/GID 10001; the Windows bind-mount
result does not establish Linux host filesystem ownership behavior.

Acceptance on 2026-09-26:

- Compose build and healthy startup passed without model keys.
- Inspection showed bind source `D:\Projects\Retrieval_SITECO\data\runtime`,
  target `/app/runtime`, read/write, host binding `127.0.0.1:8000`.
- UID 10001 committed a row to the separate `m21-acceptance.sqlite3`, closed and
  reopened it, then verified the same row after `down` and `up` replaced the
  container (different container IDs). No business schema was added to app.sqlite3.
- Stop/start and both health calls passed. Final `down` left no project container
  running; the ignored host database remains as acceptance evidence.
- Windows regression: 32 tests + 10 subtests, pip check clean. Earlier Linux test
  target: same passing suite; runtime import checks and image file inspection
  excluded test packages and private material. One known httpx warning remains.
- Earlier real local Uvicorn health and configuration failure tests also passed.
  No model calls or real key reads were needed for M2.1 acceptance.

Persistence here proves a disk path and SQLite round trip, not document-job
recovery. Dual-service proxy integration, document processing, model access and
upload-to-answer acceptance belong to subsequent M2 work.

Additional Compose checks passed with a fake key: explicit runtime injection,
HOST_PORT interpolation, and an alternate HOST_DATA_DIR actually receiving a
container-written probe in ignored `tmp/m21-compose-override`. No real key was
read or sent. `docker compose ps --all` was empty after final teardown.

## M2.2.1–2 upload identity, persistence and reception

`DocumentService` owns ID generation, SQLite metadata, durable capacity
reservations, 64 KiB file-copy chunks, SHA-256, temporary-file rename and failure
cleanup. Reception reservations use a short BEGIN IMMEDIATE transaction; file
transfer does not hold that transaction. Only after the final file exists does
one transaction create the queued document and remove its reservation. Startup
recovers leftover reservations and their files before accepting requests. This
assumes the confirmed single application process; do not run multiple workers
against this runtime directory. Storage cleanup failure returns a sanitized 503
and leaves its reservation for startup recovery rather than claiming success.

The upload adapter reserves before multipart parsing, bounds actual request
bytes (20 MiB + 64 KiB overhead), closes parser spool files, and saves the file
through the service off the event loop. Framework multipart spooling can use
system temporary storage before copying to runtime; the request bound limits
that per-upload use. The raw Content-Type is not trusted to establish file type:
accepted suffixes are PDF/CSV, PDFs need a header, and CSV structural validation
is deferred. Client path prefixes are removed from the display filename.

Added python-multipart 0.0.32 to both runtime declarations and lock. Windows and
Linux test target each passed 39 tests plus 10 subtests; pip check passed, with
the existing one Starlette/httpx deprecation warning. Tests cover identity,
reopen, exact byte boundary/oversize, last-slot concurrency, input/rename failure
cleanup, interrupted reception recovery, HTTP limits and basic type rejection.
A real Docker Compose instance using isolated D-drive tmp/m22-upload-acceptance
received two same-name CSV files with distinct IDs; after container replacement,
both queued records and exact bytes persisted. The acceptance container/network
were removed afterward. No real keys, model calls or user materials were used.

Only reception is implemented: no ready state is produced, and no processing
or retry/delete/list HTTP behavior is claimed. Full parsing and FAISS remain
uninstalled. The accepted-but-queued state currently survives startup unchanged;
M2.2.4 will implement explicit interruption handling for processing jobs.

## M2.2.3–4 lifecycle and worker

The current implementation supersedes the preceding reception-only limitations.
DocumentService now owns a bounded queue (workspace capacity), one daemon worker,
and start/stop. App lifespan starts the service before requests and shuts it down
off the event loop. Startup marks leftover queued/processing rows interrupted;
shutdown does the same and waits up to two seconds for cooperative exit. A stopped
service rejects retry and cannot publish late results. An uncooperative Python
thread cannot be killed; adapters must honor the stop event and finite timeouts.

The injected processor prepares evidence plus a retrieval manifest and restores
an index with a matching evidence-ID sequence. The lifecycle rejects empty results,
invalid evidence or mismatched mappings. Concrete parser/index adapters still own
semantic validation, vector configuration and durable raw-vector storage; FAISS
and real embeddings remain absent. The JSON document_artifacts envelope persists
evidence and the retrieval manifest for lifecycle restoration tests; it is not a
FAISS file or a replacement for the planned raw-vector BLOB storage.

Publication persists artifacts and ready status in one SQLite transaction, then
makes the index/mapping available under the same lock used by evidence readers.
Processor-owned mutable data is detached before publishing. Only complete data
can pass read_evidence; unknown IDs are 404 and unpublished data is 409. On startup,
ready artifacts are restored without calling prepare; restore failures become
index_restore_failed. No query HTTP endpoint or FAISS search is implemented yet.

retry rechecks failure eligibility and capacity atomically, preserves the upload
ID, and enqueues once; duplicate clicks receive 409. Fixed public error codes
hide processor exceptions and secrets. Default UnavailableProcessor fails with
processing_not_configured (not retryable in this build), rather than producing
fake ready data. An individual processing failure does not stop the worker.

Validation: Windows and Linux each 49 tests + 10 subtests, existing one httpx
warning, pip check clean. Controlled processors cover publication, old-ready
availability, invalid results, failure isolation, repeated retry, capacity,
startup restoration and restore failure. A real child-process kill verifies
processing_interrupted recovery; stop tests reject late publication and abandon
waiting jobs. A real Compose upload in tmp/m22-lifecycle-acceptance produced
202 then processing_not_configured while health stayed 200; its container and
network were removed. No providers or real keys were used. M2.2.5 HTTP state,
retry and evidence routes are still pending.

Docker diagnostic note: the first acceptance harness polled the live bind-mounted
SQLite from Windows while Linux was writing and observed queued beyond its two-
second deadline. A container-side short-connection check then passed, and an
asserted repeat passed both the background transition and offline host persistence.
The precise cross-system interference mechanism was not established; this is not
recorded as a proven application fix. Keep runtime database access in the backend;
use the forthcoming status API while it is running, and inspect SQLite on the host
only after the backend stops. No concurrent Windows/Linux SQLite access guarantee
is made. The initial failed harness and later passing checks are recorded in M2 log.

## M2.2.5 and M2.2 acceptance

List/detail/retry/evidence routes are now connected to DocumentService. Public
metadata is allowlisted, pagination is validated, and domain/storage/parameter
errors use sanitized code/message/retryable. Evidence responses allow only the
public evidence fields. Counts remain unknown (`progress: null`) and warnings
empty until concrete processing reports them; no timing estimates are fabricated.

Windows and Linux each passed 52 tests + 10 subtests; pip check passed. One existing
Starlette/httpx deprecation warning remains. HTTP tests cover same-name identity,
failed state and restart persistence, not-ready evidence, unknown IDs, parameter
redaction, successful retry and duplicate rejection, paused publication, evidence
pagination, and interrupted state after restart. Existing deeper lifecycle tests
cover atomic capacity and process termination; those tests are not duplicated in
each HTTP route. Linux initially exposed a test timing assumption: processing
can precede the indexing stage. The controlled adapter now signals indexing before
the test asserts that stage; Windows and Linux reruns passed.

Real Compose project siteco-m22-http, localhost18084, bind source
`tmp/m22-http-acceptance`: two same-name CSV uploads returned separate IDs and 202;
HTTP polling observed processing_not_configured, evidence/retry returned 409;
after down/up, list/detail retained both identities and errors, health was 200.
The entire runtime check used HTTP, with no host SQLite access. Container/network
were removed; ignored acceptance files remain. No model calls or real keys.

M2.2 acceptance passes for the agreed lifecycle scope. Success publication uses
controlled adapters in tests; no production fake-success path exists. Real parser,
Embedding and FAISS acceptance are deferred to their implementation steps. M2 as
a whole is still incomplete and its final dual-axis review remains pending.

## M2.3.1–2：PDF原生逐页解析

已实现app.parsing.parse_document(path, media_type, ParseLimits)及不可变结果：Evidence含文件哈希/解析版本绑定的ID、原文、物理页码、页级bbox和可选section；PageResult含extracted/degraded/no_text/failed；warnings含页码和固定原因。coverage从页面记录派生，不是语义提取率。本步使用原生页文本，尚无布局分组、降级路径或切块，因此degraded暂不会产生，bbox是整页而非精确文本区域。

逐页无可用文本则跳过，短型号不按字数丢弃。只隔离明确PDF/PS内容异常；pdfplumber包装的异常检查原始原因，OSError/RuntimeError不冒充页警告。无法打开/枚举、超过50页、全无证据明确失败；全无证据异常仍附页面记录与warnings。ID在文件或解析版本变化时更新，重复相同输入稳定。证据尚未绑定上传document_id，该关联留处理链适配器。

依赖pdfplumber0.11.10及传递版本已写入运行锁；无OCR、视觉模型或FAISS。Windows/Linux安装及pip check通过，全量58测试+10subtests通过（保留1条既有httpx提示）；最后源文件哈希调整后本机解析6测试再次通过。测试包含真实小型PDF、50/51页边界、空页与全空、坏文件、页面故障注入、存储/程序异常传播。页面异常注入只替代外部PDF库边界，不声称已覆盖所有损坏PDF。

开发材料原生提取冒烟：采购条款4/4页有文本，Rondel2/2，Highbay18/22有文本、4页no_text。复用此前PDF技能已核对的页图作为样本背景；本轮不声称布局/型号关系通过。页码标题/页脚噪声识别仍待布局步骤。未接入正式处理器、warnings持久化或HTTP；上传仍明确processing_not_configured，不直接ready。下一步M2.3.3布局分组与有限降级。

## M2.3.3–4: layout and bounded chunks

`app.parsing.parse_document` now returns page-local chunks. `text` is extracted body text; `source_spans` retain its text and bboxes; `context` retains repeated original headings/headers with their bboxes; `retrieval_text` joins context and body. Bboxes use PDF points from the top-left, and every span belongs to the Evidence physical page. The enclosing bbox can span a page title and table; use individual spans for precise highlighting. No generated facts or inferred model labels are added.

Internal character target/max are 2400/6000, pending provider token validation later. Complete table rows and top-level clauses are atomic, including continuations and indented subclauses. Oversized indivisible units are skipped with warnings; all-empty evidence fails. Uncertain regions retain native text with layout warnings. No OCR/vision or cross-page reconstruction.

Run `backend/.venv/Scripts/python.exe eval/check_m23_pdf.py` for development-sample relation checks (local data required, no API calls). Results and limitations: `eval/results/m23_layout.md`. Windows/Linux full suite: 64 tests plus 10 subtests. This parser is not connected to the production worker yet; upload does not become ready merely from parsing. Coverage/warnings persistence and HTTP exposure remain subsequent work.

## M2.3.6 supersedes the preceding integration limitation

PDF parsing is now wired into the production worker. Parsed evidence, source/context spans, page outcomes and warnings are saved atomically to document_parses, separately from published retrieval artifacts. List/detail return only parsing summaries and warnings; the evidence endpoint remains ready-only. A parsed PDF ends with retrieval_not_configured until embedding/indexing is implemented; CSV remains processing_not_configured. Invalid PDFs have fixed public errors. No parser exception text or internal paths are returned.

Retry clears the previous parse checkpoint; interruption preserves a checkpoint already committed, but late reports cannot overwrite it. Restart does not automatically parse again. Final Windows/Linux: 69 tests + 10 subtests. Real Docker Highbay upload/restart and HTTP summary persistence passed; see eval/results/m23_layout.md. M2.3 is accepted only for PDF-to-evidence/coverage, not ready/query completion.
