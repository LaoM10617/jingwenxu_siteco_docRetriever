"""Persist accepted uploads and reserve capacity before reading their contents."""
from contextlib import closing
from datetime import datetime, timezone
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import sqlite3
import json
import logging
from queue import Queue, Empty
from threading import RLock, Event, Thread

from app.processing import PreparedDocument, ProcessingFailure, DocumentProcessor
from app.csv_parsing import ParsedCsvDocument
from app.csv_store import CsvStore, summary
from app.pdf_store import PdfStore, PreparedPdf, PdfIndex, normalize
from uuid import uuid4

MAX_FILE_BYTES = 20 * 1024 * 1024


class DocumentError(Exception):
    def __init__(self, code, message, status_code, retryable=False):
        super().__init__(message)
        self.code, self.status_code, self.retryable = code, status_code, retryable


class DocumentService:
    def __init__(self, runtime: Path, *, max_bytes=MAX_FILE_BYTES, max_documents=10):
        self.uploads = runtime / 'uploads'
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.database = runtime / 'app.sqlite3'
        self.max_bytes, self.max_documents = max_bytes, max_documents
        self._lock = RLock()
        self._stop = Event()
        self._jobs = Queue(maxsize=max_documents)
        self._thread = None
        self._published = {}
        self._csv_ready = set()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY, original_filename TEXT NOT NULL,
                stored_name TEXT NOT NULL, size_bytes INTEGER, content_hash TEXT,
                status TEXT NOT NULL, stage TEXT NOT NULL, error_code TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            db.execute('CREATE TABLE IF NOT EXISTS upload_reservations (document_id TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE IF NOT EXISTS document_artifacts (document_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS document_parses (document_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self._csv = CsvStore(self.database)
        self._pdf = PdfStore(self.database)
        from app.retrieval.pdf import FtsStore
        self.lexical = FtsStore(self.database)

    def reserve(self):
        """Reserve one slot atomically, including requests still receiving bytes."""
        document_id = uuid4().hex
        try:
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                count = db.execute("SELECT COUNT(*) FROM documents WHERE status IN ('queued','processing','ready')").fetchone()[0]
                count += db.execute('SELECT COUNT(*) FROM upload_reservations').fetchone()[0]
                if count >= self.max_documents:
                    raise DocumentError('document_limit_reached', 'The workspace has no free document slots.', 409)
                db.execute('INSERT INTO upload_reservations VALUES (?)', (document_id,))
        except sqlite3.Error:
            raise DocumentError('storage_unavailable', 'Cannot reserve upload storage.', 503, True) from None
        return document_id

    def discard(self, document_id):
        """Release an unaccepted upload; never remove an accepted document."""
        with closing(sqlite3.connect(self.database)) as db, db:
            if db.execute('SELECT 1 FROM documents WHERE document_id=?', (document_id,)).fetchone():
                return
            (self.uploads / (document_id + '.part')).unlink(missing_ok=True)
            (self.uploads / document_id).unlink(missing_ok=True)
            db.execute('DELETE FROM upload_reservations WHERE document_id=?', (document_id,))

    def recover_receiving(self):
        """Called once at startup, before requests: discard interrupted reception."""
        with closing(sqlite3.connect(self.database)) as db:
            ids = [row[0] for row in db.execute('SELECT document_id FROM upload_reservations')]
        for document_id in ids:
            self.discard(document_id)

    def submit(self, filename, source, *, reservation=None):
        document_id = reservation or self.reserve()
        temporary = self.uploads / (document_id + '.part')
        destination = self.uploads / document_id
        try:
            filename = (filename or '').replace('\\', '/').rsplit('/', 1)[-1]
            extension = Path(filename).suffix.lower()
            if extension not in {'.pdf', '.csv'}:
                raise DocumentError('unsupported_file_type', 'Only PDF and CSV files are supported.', 415)
            digest, size, prefix = sha256(), 0, b''
            with temporary.open('xb') as output:
                while block := source.read(64 * 1024):
                    size += len(block)
                    if size > self.max_bytes:
                        raise DocumentError('file_too_large', 'File exceeds the upload size limit.', 413)
                    prefix = (prefix + block)[:1024]
                    output.write(block)
                    digest.update(block)
            if size == 0:
                raise DocumentError('empty_file', 'The uploaded file is empty.', 422)
            if extension == '.pdf' and b'%PDF-' not in prefix:
                raise DocumentError('invalid_pdf_header', 'The file does not have a PDF header.', 415)
            # CSV has no reliable magic signature; structural validation belongs to parsing.
            temporary.replace(destination)
            now = datetime.now(timezone.utc).isoformat()
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (document_id, filename, document_id, size, digest.hexdigest(),
                            'queued', 'queued', None, now, now))
                db.execute('DELETE FROM upload_reservations WHERE document_id=?', (document_id,))
            document = self.get(document_id)
            with self._lock:
                if self._thread is not None:
                    if self._stop.is_set():
                        self._fail(document_id, 'processing_interrupted')
                    else:
                        self._jobs.put_nowait(document_id)
            return document
        except (OSError, sqlite3.Error):
            raise DocumentError('storage_unavailable', 'Cannot save the uploaded file.', 503, True) from None
        finally:
            try:
                self.discard(document_id)
            except (OSError, sqlite3.Error):
                # Keep the durable reservation for startup recovery if cleanup cannot run.
                raise DocumentError('storage_unavailable', 'Upload cleanup could not complete.', 503, True) from None

    def get(self, document_id):
        with self._lock, closing(sqlite3.connect(self.database)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM documents WHERE document_id=?', (document_id,)).fetchone()
            parsed = db.execute('SELECT payload FROM document_parses WHERE document_id=?', (document_id,)).fetchone()
        if row is None:
            return None
        document = dict(row)
        document['parse_result'] = json.loads(parsed[0]) if parsed else None
        code = document['error_code']
        document['error'] = None if code is None else {
            'code': code, 'message': ERRORS.get(code, ERRORS['processing_failed'])[0],
            'retryable': ERRORS.get(code, ERRORS['processing_failed'])[1]}
        return document


    def list(self):
        with self._lock, closing(sqlite3.connect(self.database)) as db:
            ids = db.execute('SELECT document_id FROM documents ORDER BY created_at, document_id').fetchall()
            return [self.get(document_id) for (document_id,) in ids]

    def start(self, processor=None):
        """One worker per service/process. Restore completed data before serving."""
        with self._lock:
            if self._thread is not None:
                raise RuntimeError('Document service cannot be started twice')
            self._processor = processor if processor is not None else DocumentProcessor()
            self.recover_receiving()
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute("UPDATE documents SET status='failed', stage='failed', error_code='processing_interrupted', updated_at=? WHERE status IN ('queued','processing')", (self._now(),))
                ready = db.execute("SELECT document_id FROM documents WHERE status='ready'").fetchall()
                # Rebuild only from validated, published artifacts before serving.
                db.execute('DELETE FROM pdf_fts')
            for (document_id,) in ready:
                try:
                    if self._csv.restore(document_id, self.get(document_id)['parse_result']):
                        self._csv_ready.add(document_id)
                        continue
                    pdf = self._pdf.restore(document_id)
                    if pdf is not None:
                        self.lexical.replace_document(document_id, pdf[0].evidence)
                        self._published[document_id] = pdf
                        continue
                    with closing(sqlite3.connect(self.database)) as db:
                        payload = db.execute('SELECT payload FROM document_artifacts WHERE document_id=?', (document_id,)).fetchone()
                    prepared = PreparedDocument(**json.loads(payload[0]))
                    index = self._build_index(prepared)
                    self._published[document_id] = (prepared, index)
                except Exception:
                    self._fail(document_id, 'index_restore_failed')
            self._thread = Thread(target=self._work, name='document-ingestion', daemon=True)
            self._thread.start()

    def stop(self):
        """Cooperative cancellation; a late processor result can never publish."""
        with self._lock:
            self._stop.set()
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute("UPDATE documents SET status='failed', stage='failed', error_code='processing_interrupted', updated_at=? WHERE status IN ('queued','processing')", (self._now(),))
        if self._thread is not None:
            self._thread.join(timeout=2)
        # Providers must eventually honor timeouts/stop. Threads cannot be force-killed.

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _fail(self, document_id, code):
        code = code if code in ERRORS else 'processing_failed'
        with self._lock, closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE documents SET status='failed', stage='failed', error_code=?, updated_at=? WHERE document_id=? AND status IN ('queued','processing','ready')",
                       (code, self._now(), document_id))
            self._published.pop(document_id, None)
            self._csv_ready.discard(document_id)
            db.execute('DELETE FROM pdf_fts WHERE document_id=?', (document_id,))

    def _build_index(self, prepared):
        # The concrete adapter additionally validates its vector/CSV schema.
        if not isinstance(prepared, PreparedDocument) or not prepared.evidence or not prepared.retrieval_data:
            raise ProcessingFailure('incomplete_result')
        ids = [item['evidence_id'] for item in prepared.evidence]
        if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i for i in ids):
            raise ProcessingFailure('incomplete_result')
        if any(not isinstance(item.get('text'), str) or not item['text'].strip() or not isinstance(item.get('locator'), dict) for item in prepared.evidence):
            raise ProcessingFailure('incomplete_result')
        index = self._processor.restore(prepared)
        if tuple(index.evidence_ids) != tuple(ids):
            raise ProcessingFailure('incomplete_result')
        return index

    def _report(self, document_id, stage, *, parsed=None):
        if stage not in {'parsing', 'embedding', 'waiting_rate_limit', 'indexing'}:
            raise ProcessingFailure('processing_failed')
        with self._lock:
            if self._stop.is_set():
                raise ProcessingFailure('processing_interrupted')
            with closing(sqlite3.connect(self.database)) as db, db:
                changed = db.execute("UPDATE documents SET stage=?, updated_at=? WHERE document_id=? AND status='processing'", (stage, self._now(), document_id)).rowcount
                if not changed:
                    raise ProcessingFailure('processing_interrupted')
                if parsed is not None:
                    db.execute('INSERT OR REPLACE INTO document_parses VALUES (?,?)',
                               (document_id, json.dumps(summary(parsed) if isinstance(parsed, ParsedCsvDocument) else asdict(parsed), allow_nan=False)))

    def _work(self):
        while not self._stop.is_set():
            try:
                document_id = self._jobs.get(timeout=.1)
            except Empty:
                continue
            try:
                with self._lock:
                    if self._stop.is_set():
                        continue
                    with closing(sqlite3.connect(self.database)) as db, db:
                        changed = db.execute("UPDATE documents SET status='processing', stage='parsing', updated_at=? WHERE document_id=? AND status='queued'", (self._now(), document_id)).rowcount
                    if not changed:
                        continue
                document = self.get(document_id)
                prepared = self._processor.prepare(self.uploads / document['stored_name'], document,
                    lambda stage, **kwargs: self._report(document_id, stage, **kwargs), self._stop)
                if isinstance(prepared, PreparedPdf):
                    # Detach evidence and vectors before validation/publication.
                    prepared = PreparedPdf(json.loads(json.dumps(prepared.evidence, allow_nan=False)),
                                           normalize(prepared.vectors))
                    index = PdfIndex(prepared)
                    with self._lock:
                        if self._stop.is_set():
                            continue
                        with closing(sqlite3.connect(self.database)) as db, db:
                            self._pdf.write(db, document_id, prepared)
                            self.lexical.replace_document(document_id, prepared.evidence, connection=db)
                            changed = db.execute("UPDATE documents SET status='ready', stage='ready', error_code=NULL, updated_at=? WHERE document_id=? AND status='processing'", (self._now(), document_id)).rowcount
                            if not changed:
                                raise ProcessingFailure('processing_interrupted')
                        self._published[document_id] = (prepared, index)
                    continue
                if isinstance(prepared, ParsedCsvDocument):
                    self._csv.stage(document_id, prepared)
                    if not self._csv.restore(document_id, self.get(document_id)['parse_result']):
                        raise ProcessingFailure('incomplete_result')
                    with self._lock:
                        if self._stop.is_set():
                            continue
                        with closing(sqlite3.connect(self.database)) as db, db:
                            changed = db.execute("UPDATE documents SET status='ready', stage='ready', error_code=NULL, updated_at=? WHERE document_id=? AND status='processing'", (self._now(), document_id)).rowcount
                        if changed:
                            self._csv_ready.add(document_id)
                    continue
                if not isinstance(prepared, PreparedDocument):
                    raise ProcessingFailure('incomplete_result')
                # Detach the result from mutable objects retained by the processor.
                payload = json.dumps({'evidence': prepared.evidence, 'retrieval_data': prepared.retrieval_data}, allow_nan=False)
                prepared = PreparedDocument(**json.loads(payload))
                index = self._build_index(prepared)
                with self._lock:
                    if self._stop.is_set():
                        continue
                    with closing(sqlite3.connect(self.database)) as db, db:
                        db.execute('INSERT OR REPLACE INTO document_artifacts VALUES (?,?)', (document_id, payload))
                        db.execute("UPDATE documents SET status='ready', stage='ready', error_code=NULL, updated_at=? WHERE document_id=? AND status='processing'", (self._now(), document_id))
                    self._published[document_id] = (prepared, index)
            except Exception as exc:
                try:
                    self._fail(document_id, exc.code if isinstance(exc, ProcessingFailure) else 'processing_failed')
                except sqlite3.Error:
                    # Storage may be unavailable; do not kill the worker or expose inputs.
                    logging.getLogger(__name__).error('Cannot persist processing failure; restart recovery required')
            finally:
                self._jobs.task_done()

    def retry(self, document_id):
        with self._lock, closing(sqlite3.connect(self.database)) as db, db:
            if self._thread is None or self._stop.is_set():
                raise DocumentError('processing_unavailable', 'Processing is not running.', 503, True)
            db.execute('BEGIN IMMEDIATE')
            document = db.execute('SELECT status,error_code FROM documents WHERE document_id=?', (document_id,)).fetchone()
            if document is None:
                raise DocumentError('document_not_found', 'Unknown document ID.', 404)
            if document[0] != 'failed' or not ERRORS.get(document[1], ('', False))[1]:
                raise DocumentError('retry_not_allowed', 'This document cannot be retried now.', 409)
            count = db.execute("SELECT COUNT(*) FROM documents WHERE status IN ('queued','processing','ready')").fetchone()[0]
            count += db.execute('SELECT COUNT(*) FROM upload_reservations').fetchone()[0]
            if count >= self.max_documents:
                raise DocumentError('document_limit_reached', 'The workspace has no free document slots.', 409)
            db.execute("UPDATE documents SET status='queued', stage='queued', error_code=NULL, updated_at=? WHERE document_id=?", (self._now(), document_id))
            db.execute('DELETE FROM document_parses WHERE document_id=?', (document_id,))
            self._csv.clear(db, document_id)
            self._pdf.clear(db, document_id)
            db.execute('DELETE FROM pdf_fts WHERE document_id=?', (document_id,))
            db.execute('DELETE FROM document_artifacts WHERE document_id=?', (document_id,))
            db.commit()
            self._jobs.put_nowait(document_id)
            return self.get(document_id)

    def read_evidence(self, document_id, offset=0, limit=20):
        if offset < 0 or not 1 <= limit <= 100:
            raise DocumentError('invalid_pagination', 'Invalid evidence pagination.', 422)
        with self._lock:
            document = self.get(document_id)
            if document is None:
                raise DocumentError('document_not_found', 'Unknown document ID.', 404)
            if document['status'] != 'ready' or document_id not in self._published and document_id not in self._csv_ready:
                raise DocumentError('document_not_ready', 'The document is not available for queries.', 409)
            if document_id in self._csv_ready:
                return self._csv.read(document_id, offset, limit)
            prepared, _ = self._published[document_id]
            return json.loads(json.dumps(prepared.evidence[offset:offset + limit]))

    @property
    def stop_event(self):
        return self._stop

    def pdf_snapshot(self, document_ids):
        with self._lock:
            result = {}
            for identity in document_ids:
                document = self.get(identity)
                published = self._published.get(identity)
                if document is None or document['status'] != 'ready':
                    raise DocumentError('document_not_ready', 'The document is not available for queries.', 409)
                if published is None or not isinstance(published[1], PdfIndex):
                    raise DocumentError('retrieval_not_configured', 'PDF vectors are not available.', 503)
                result[identity] = published
            return result

    def pdf_lexical(self, question, scope, snapshots, limit):
        with self._lock:
            current = self.pdf_snapshot(scope)
            if any(current[key] is not snapshots[key] for key in scope):
                raise DocumentError('document_not_ready', 'The document publication changed; retry the query.', 409, True)
            return self.lexical.search(question, scope, limit)

    def lookup_orders(self, order_ids, document_ids, offset=0, limit=50):
        if (not isinstance(order_ids, list) or not order_ids
                or any(not isinstance(v, str) or not v.strip() for v in order_ids)
                or not isinstance(document_ids, list) or not document_ids
                or any(not isinstance(v, str) or not v for v in document_ids)):
            raise DocumentError('invalid_query', 'Provide nonempty string order IDs and explicit document IDs.', 422)
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
            raise DocumentError('invalid_pagination', 'Invalid query pagination.', 422)
        orders = list(dict.fromkeys(v.strip() for v in order_ids))
        documents = list(dict.fromkeys(document_ids))
        with self._lock:
            for document_id in documents:
                document = self.get(document_id)
                if document is None:
                    raise DocumentError('document_not_found', 'Unknown document ID.', 404)
                if document['status'] != 'ready':
                    raise DocumentError('document_not_ready', 'The document is not available for queries.', 409)
                if document_id not in self._csv_ready:
                    raise DocumentError('document_not_csv', 'Exact order lookup requires a CSV document.', 422)
            return self._csv.lookup(orders, documents, offset, limit)


ERRORS = {
    'embedding_configuration_invalid': ('Voyage-4 requires the pinned tokenizer in DATA_DIR/tokenizers.', False),
    'embedding_authentication_failed': ('Embedding authentication failed; check the backend key.', True),
    'embedding_rate_limited': ('Embedding quota remained unavailable after bounded retries.', True),
    'embedding_provider_unavailable': ('Embedding provider timed out or is unavailable.', True),
    'embedding_provider_error': ('Embedding provider rejected the request.', True),
    'embedding_invalid_vectors': ('Embedding returned invalid vectors.', True),
    'embedding_invalid_usage': ('Embedding returned invalid usage information.', True),
    'embedding_invalid_input': ('Embedding input is invalid.', False),
    'embedding_input_too_large': ('An evidence chunk exceeds the embedding token budget.', False),
    'embedding_queue_full': ('Embedding queue is full; retry later.', True),
    'embedding_wait_timeout': ('Embedding quota wait timed out; retry later.', True),
    'embedding_interrupted': ('Embedding was interrupted; retry the document.', True),
    'csv_header_invalid': ('CSV headers do not match the supported price-list schema.', False),
    'csv_record_limit': ('CSV exceeds the 20,000 record limit.', False),
    'csv_record_invalid': ('CSV record has the wrong number of fields.', False),
    'csv_no_records': ('CSV contains no data records.', False),
    'csv_encoding_invalid': ('CSV must use UTF-8 encoding.', False),
    'csv_unreadable': ('CSV quoting is invalid or a field exceeds the reader limit.', False),
    'csv_no_order_ids': ('CSV contains no searchable order IDs; inspect the retained warnings.', False),
    'retrieval_not_configured': ('PDF parsing completed; embedding and retrieval are not configured in this build.', False),
    'pdf_unreadable': ('Cannot open the PDF; it may be damaged or encrypted.', False),
    'pdf_pages_unreadable': ('Cannot reliably enumerate PDF pages.', False),
    'pdf_page_limit': ('PDF exceeds the page limit.', False),
    'no_usable_evidence': ('No usable native-text evidence was extracted.', False),
    'processing_not_configured': ('Document processing is not configured in this build.', False),
    'processing_interrupted': ('Processing was interrupted; retry the document.', True),
    'processing_failed': ('Document processing failed; retry or check the file.', True),
    'incomplete_result': ('Processing did not produce complete queryable data.', False),
    'index_restore_failed': ('Stored query data could not be restored.', True),
}
