"""Minimal API with local storage checks before serving requests."""

from contextlib import asynccontextmanager, closing
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import sqlite3
import tempfile
import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import Settings, load_settings
from app.documents import DocumentService, DocumentError
from app.sessions import SessionStore
from app.artifacts import ArtifactStore
from app.session_api import router as session_router
from app.uploads import router
from app.processing import DocumentProcessor
from app.retrieval.pdf import PdfRetriever
from app.reranking import configured_reranker
from app.runtime_settings import MemorySettings, router as settings_router
from app.runtime_bindings import RuntimeBindings
from app.voyage import configured_gateway
from app.questions import QuestionTools
from app.answers import AnswerService
from app.generation import StructuredModel
from app.conversation_runs import ConversationRuns
from app.pdf_specialist import PdfSpecialist
from app.run_api import router as run_router, developer_router
from app.run_cleanup import retry_purges
from app.execution_jobs import ExecutionJobs
from app.execution_api import router as execution_router

VERSION = "0.1.0"


class StartupError(RuntimeError):
    """A local startup failure safe to show without configuration values."""


def create_app(settings: Settings | None = None, *, processor=None, model=None) -> FastAPI:
    """Construct the application; check storage only when lifespan starts."""
    configuration = settings if settings is not None else load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        events = logging.getLogger('siteco.providers')
        if not events.handlers:
            events.addHandler(logging.StreamHandler())
        events.setLevel(logging.INFO)
        events.propagate = False
        try:
            configuration.data_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=configuration.data_dir, prefix=".write-check-",
            ) as probe:
                probe.write(b"startup check")
                probe.flush()
        except OSError:
            raise StartupError("DATA_DIR is not writable; check the directory and permissions") from None
        try:
            with closing(sqlite3.connect(configuration.data_dir / "app.sqlite3", timeout=1)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                connection.execute(f"PRAGMA user_version = {version}")
                connection.rollback()
        except sqlite3.Error:
            raise StartupError("SQLite startup check failed; check app.sqlite3, permissions and locks") from None
        try:
            app.state.documents = DocumentService(configuration.data_dir)
            app.state.sessions = SessionStore(app.state.documents.database)
            app.state.documents.lifecycle = app.state.sessions
            app.state.artifacts = ArtifactStore(app.state.documents.database)
            app.state.documents.derived = app.state.artifacts
            bindings = RuntimeBindings(app.state.memory_settings, app.state.documents, processor=processor, model=model)
            app.state.bindings = bindings
            app.state.documents.processor_factory = bindings.processor
            app.state.answers = bindings.answers()
            app.state.retriever = app.state.answers.tools.retriever
            await run_in_threadpool(app.state.documents.start, processor if processor is not None else DocumentProcessor())
            app.state.execution_jobs = ExecutionJobs(app.state.documents.database,
                                                    expected_image=configuration.execution_image)
            def csv_specialist(service):
                if not configuration.execution_image or not configuration.execution_worker_token:
                    raise DocumentError('csv_execution_not_configured', 'Configure the CSV execution worker and image.', 503)
                from app.csv_specialist import CsvSpecialist
                return CsvSpecialist(service, app.state.execution_jobs, app.state.artifacts)
            app.state.runs = ConversationRuns(app.state.documents.database, bindings, PdfSpecialist,
                                             csv_specialist_factory=csv_specialist)
            retry_purges(app.state.runs)
            app.state.run_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='conversation')
            app.state.run_schedule_lock = Lock()
            app.state.scheduled_runs = set()
        except (OSError, sqlite3.Error):
            raise StartupError("Upload storage initialization failed; check permissions and database") from None
        try:
            yield
        finally:
            app.state.runs.shutdown()
            await run_in_threadpool(app.state.run_executor.shutdown, wait=True)
            await run_in_threadpool(app.state.documents.stop)

    app = FastAPI(title="SITECO Document Retriever", version=VERSION, lifespan=lifespan)
    @app.middleware('http')
    async def settings_no_store(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/settings'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    app.state.settings = configuration
    app.state.memory_settings = MemorySettings(configuration)
    app.include_router(settings_router)
    app.include_router(router)
    app.include_router(session_router)
    app.include_router(run_router)
    app.include_router(developer_router)
    app.include_router(execution_router)

    @app.exception_handler(DocumentError)
    async def document_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={
            'error': {'code': exc.code, 'message': str(exc), 'retryable': exc.retryable}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, content={
            'error': {'code': 'invalid_request', 'message': 'Invalid request parameters.', 'retryable': False}})

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def storage_error(request, exc):
        return JSONResponse(status_code=503, content={
            'error': {'code': 'storage_unavailable', 'message': 'Document storage is unavailable.', 'retryable': True}})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": VERSION}

    return app
