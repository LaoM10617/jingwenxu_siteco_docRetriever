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
