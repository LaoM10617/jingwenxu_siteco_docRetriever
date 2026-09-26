"""Minimal API with local storage checks before serving requests."""

from contextlib import asynccontextmanager, closing
import sqlite3
import tempfile
import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import Settings, load_settings
from app.documents import DocumentService, DocumentError
from app.uploads import router
from app.processing import DocumentProcessor
from app.retrieval.pdf import PdfRetriever
from app.voyage import configured_gateway
from app.questions import QuestionTools
from app.answers import AnswerService
from app.generation import StructuredModel
from app.question_tasks import QuestionTasks, router as question_router

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
            gateway = configured_gateway(configuration) if processor is None else getattr(processor, 'gateway', None)
            app.state.retriever = PdfRetriever(app.state.documents, app.state.documents.lexical, gateway)
            app.state.answers = AnswerService(QuestionTools(app.state.documents, app.state.retriever),
                                             model if model is not None else StructuredModel(configuration))
            await run_in_threadpool(app.state.documents.start, processor if processor is not None else DocumentProcessor(gateway))
            app.state.questions = QuestionTasks(configuration.data_dir / 'app.sqlite3', app.state.answers)
        except (OSError, sqlite3.Error):
            raise StartupError("Upload storage initialization failed; check permissions and database") from None
        try:
            yield
        finally:
            await run_in_threadpool(app.state.questions.stop)
            await run_in_threadpool(app.state.documents.stop)

    app = FastAPI(title="SITECO Document Retriever", version=VERSION, lifespan=lifespan)
    app.state.settings = configuration
    app.include_router(router)
    app.include_router(question_router)

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
