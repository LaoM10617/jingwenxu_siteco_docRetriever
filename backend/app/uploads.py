"""HTTP upload adapter: reserve before receiving and bound multipart spooling."""
import sqlite3

from fastapi import APIRouter, Request, Query
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.requests import ClientDisconnect

from app.documents import DocumentError, MAX_FILE_BYTES

router = APIRouter()


@router.post('/api/documents', status_code=202)
async def upload_document(request: Request):
    service = request.app.state.documents
    reservation = None
    try:
        reservation = await run_in_threadpool(service.reserve)
        received = 0

        async def receive():
            nonlocal received
            message = await request.receive()
            received += len(message.get('body', b''))
            if received > MAX_FILE_BYTES + 64 * 1024:
                raise DocumentError('file_too_large', 'Upload request exceeds the size limit.', 413)
            return message

        bounded = Request(request.scope, receive)
        async with bounded.form(max_files=1, max_fields=0) as form:
            items = form.multi_items()
            if len(items) != 1 or items[0][0] != 'file' or not isinstance(items[0][1], UploadFile):
                raise DocumentError('invalid_upload', 'Provide exactly one file field.', 422)
            file = items[0][1]
            document = await run_in_threadpool(service.submit, file.filename, file.file, reservation=reservation)
            return {key: document[key] for key in ('document_id', 'original_filename', 'status')}
    except DocumentError as exc:
        return JSONResponse(status_code=exc.status_code, content={
            'error': {'code': exc.code, 'message': str(exc), 'retryable': exc.retryable}})
    except (OSError, sqlite3.Error):
        return JSONResponse(status_code=503, content={
            'error': {'code': 'storage_unavailable', 'message': 'Upload storage is unavailable.', 'retryable': True}})
    except (HTTPException, ClientDisconnect):
        return JSONResponse(status_code=422, content={
            'error': {'code': 'invalid_upload', 'message': 'A complete single-file multipart upload is required.', 'retryable': False}})
    finally:
        if reservation is not None:
            try:
                await run_in_threadpool(service.discard, reservation)
            except (OSError, sqlite3.Error):
                return JSONResponse(status_code=503, content={
                    'error': {'code': 'storage_unavailable', 'message': 'Upload cleanup could not complete.', 'retryable': True}})


def public_document(document):
    result = {key: document[key] for key in (
        'document_id', 'original_filename', 'size_bytes', 'status', 'stage',
        'error', 'created_at', 'updated_at')}
    result['media_type'] = 'application/pdf' if document['original_filename'].lower().endswith('.pdf') else 'text/csv'
    # Counts are unknown until the processing adapter reports them.
    result['progress'] = None
    result['warnings'] = []
    return result


@router.get('/api/documents')
def list_documents(request: Request):
    return [public_document(doc) for doc in request.app.state.documents.list()]


@router.get('/api/documents/{document_id}')
def document_status(document_id: str, request: Request):
    document = request.app.state.documents.get(document_id)
    if document is None:
        raise DocumentError('document_not_found', 'Unknown document ID.', 404)
    return public_document(document)


@router.post('/api/documents/{document_id}/retry', status_code=202)
def retry_document(document_id: str, request: Request):
    return public_document(request.app.state.documents.retry(document_id))


@router.get('/api/documents/{document_id}/evidence')
def document_evidence(document_id: str, request: Request,
                      offset: int = Query(default=0, ge=0),
                      limit: int = Query(default=20, ge=1, le=100)):
    evidence = request.app.state.documents.read_evidence(document_id, offset, limit)
    return [{key: item[key] for key in ('evidence_id', 'text', 'locator', 'raw_values') if key in item}
            for item in evidence]
