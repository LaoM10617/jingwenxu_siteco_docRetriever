"""Processing result contract; concrete parsers and search indexes arrive later."""
from dataclasses import dataclass
from typing import Any


@dataclass
class PreparedDocument:
    evidence: list[dict[str, Any]]
    retrieval_data: dict[str, Any]


class ProcessingFailure(Exception):
    """Only fixed, public failure codes are accepted by the lifecycle owner."""
    def __init__(self, code):
        self.code = code


class UnavailableProcessor:
    def prepare(self, path, document, report, stop):
        raise ProcessingFailure('processing_not_configured')

    def restore(self, prepared):
        raise ProcessingFailure('processing_not_configured')


class PdfParsingProcessor(UnavailableProcessor):
    """Persist a parse checkpoint, but never pretend that an index exists."""
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
        raise ProcessingFailure('retrieval_not_configured')
