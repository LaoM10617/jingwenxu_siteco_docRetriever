from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class PreparedDocument:
    evidence: list[dict[str, Any]]
    retrieval_data: dict[str, Any]


class ProcessingFailure(Exception):
    def __init__(self, code):
        self.code = code


class UnavailableProcessor:
    def prepare(self, path, document, report, stop):
        raise ProcessingFailure('processing_not_configured')

    def restore(self, prepared):
        raise ProcessingFailure('processing_not_configured')


class PdfParsingProcessor(UnavailableProcessor):
    """Persist the parse checkpoint before potentially waiting for embeddings."""
    def __init__(self, gateway=None):
        self.gateway = gateway

    def prepare(self, path, document, report, stop):
        from app.parsing import parse_document, ParseLimits, ParseError, ParsedDocument
        if not document['original_filename'].lower().endswith('.pdf'):
            raise ProcessingFailure('processing_not_configured')
        if stop.is_set():
            raise ProcessingFailure('processing_interrupted')
        try:
            parsed = parse_document(path, 'application/pdf', ParseLimits())
        except ParseError as exc:
            report('parsing', parsed=ParsedDocument((), exc.pages, exc.warnings))
            raise ProcessingFailure(exc.code) from None
        report('parsing', parsed=parsed)
        if self.gateway is None:
            raise ProcessingFailure('retrieval_not_configured')
        from app.embeddings import EmbeddingError
        from app.pdf_store import PreparedPdf
        evidence = []
        for entry in parsed.evidence:
            row = asdict(entry)
            row['locator'] = {'kind': 'pdf', 'page_number': row.pop('page_number'),
                              'bbox': row.pop('bbox')}
            evidence.append(row)
        report('embedding')
        try:
            vectors = self.gateway.embed([e['retrieval_text'] or e['text'] for e in evidence],
                input_type='document', stop=stop, on_wait=lambda: report('waiting_rate_limit'),
                on_start=lambda: report('embedding'))
        except EmbeddingError as exc:
            raise ProcessingFailure(exc.code) from None
        report('indexing')
        return PreparedPdf(evidence, vectors)


class DocumentProcessor(PdfParsingProcessor):
    def prepare(self, path, document, report, stop):
        if not document['original_filename'].lower().endswith('.csv'):
            return super().prepare(path, document, report, stop)
        from app.parsing import parse_document, ParseLimits, ParseError
        if stop.is_set():
            raise ProcessingFailure('processing_interrupted')
        try:
            parsed = parse_document(path, 'text/csv', ParseLimits())
        except ParseError as exc:
            raise ProcessingFailure(exc.code) from None
        report('parsing', parsed=parsed)
        if not any(r.order_id for r in parsed.records):
            raise ProcessingFailure('csv_no_order_ids')
        report('indexing')
        return parsed
