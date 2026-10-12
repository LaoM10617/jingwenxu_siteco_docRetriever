"""Document parsing entry point; PDF evidence and CSV records retain their own locators."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from .csv_parsing import ParsedCsvDocument

import pdfplumber
from pdfminer.psexceptions import PSException
from pdfplumber.utils.exceptions import PdfminerException, MalformedPDFException
from .pdf_layout import group_page, SourceSpan, Region

PARSER_VERSION = 'layout-chunks-v2/pdfplumber-' + pdfplumber.__version__
PageStatus = Literal['extracted', 'degraded', 'no_text', 'failed']
# Internal character budgets, not provider token limits. Versioned with evidence IDs.
CHUNK_TARGET = 2400
CHUNK_MAX = 6000


@dataclass(frozen=True)
class ParseLimits:
    max_pages: int = 50
    max_records: int = 20_000


@dataclass(frozen=True)
class ParseWarning:
    page_number: int
    code: str
    message: str


@dataclass(frozen=True)
class PageResult:
    page_number: int
    status: PageStatus


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    text: str
    page_number: int
    bbox: tuple[float, float, float, float]
    section: str | None = None
    retrieval_text: str = ''
    source_spans: tuple[SourceSpan, ...] = ()
    context: tuple[SourceSpan, ...] = ()


@dataclass(frozen=True)
class ParsedDocument:
    evidence: tuple[Evidence, ...]
    pages: tuple[PageResult, ...]
    warnings: tuple[ParseWarning, ...]
    parser_version: str = PARSER_VERSION
    reading: dict | None = None

    @property
    def page_count(self):
        return len(self.pages)

    @property
    def coverage(self):
        counts = Counter(page.status for page in self.pages)
        return {status: counts[status] for status in ('extracted', 'degraded', 'no_text', 'failed')}


class ParseError(Exception):
    def __init__(self, code, message, *, pages=(), warnings=()):
        super().__init__(message)
        self.code, self.pages, self.warnings = code, tuple(pages), tuple(warnings)


def _content_error(exc):
    # pdfplumber wraps even OSError/programming errors: inspect the actual cause.
    if isinstance(exc, PdfminerException):
        cause = exc.__cause__ or exc.__context__
        if cause is None and exc.args and isinstance(exc.args[0], Exception):
            cause = exc.args[0]
        return isinstance(cause, (PSException, MalformedPDFException))
    return isinstance(exc, (PSException, MalformedPDFException))


def _chunks(region):
    header, units = region.header, region.units
    if not units:
        units, header = header, ()
    prefix = '\n'.join(s.text for s in header)
    batch = []
    for unit in units:
        if len(prefix) + len(unit.text) + 1 > CHUNK_MAX:
            if batch:
                yield header, tuple(batch)
                batch = []
            yield None, None
            continue
        if batch and len(prefix) + sum(len(s.text) + 1 for s in batch) + len(unit.text) + 1 > CHUNK_TARGET:
            yield header, tuple(batch)
            batch = []
        batch.append(unit)
    if batch:
        yield header, tuple(batch)


def _page_evidence(regions, content_hash, number):
    evidence, omitted = [], False
    for index, region in enumerate(regions):
        for part, (context, sources) in enumerate(_chunks(region)):
            if sources is None:
                omitted = True
                continue
            body = '\n'.join(s.text for s in sources)
            retrieval = '\n'.join(s.text for s in context + sources)
            locations = context + sources
            box = (min(s.bbox[0] for s in locations), min(s.bbox[1] for s in locations),
                   max(s.bbox[2] for s in locations), max(s.bbox[3] for s in locations))
            identity = sha256(f'{content_hash}\0{PARSER_VERSION}\0{CHUNK_TARGET}/{CHUNK_MAX}\0{number}\0{index}/{part}\0{retrieval}'.encode()).hexdigest()
            evidence.append(Evidence(identity, body, number, box,
                                     '\n'.join(s.text for s in context) or None,
                                     retrieval, sources, context))
    return evidence, omitted


def parse_document(stored_file: Path, media_type: str, limits: ParseLimits, *, check=None) -> ParsedDocument | ParsedCsvDocument:
    if media_type == 'text/csv':
        from .csv_parsing import parse_csv
        return parse_csv(stored_file, limits.max_records)
    if media_type != 'application/pdf':
        raise ParseError('unsupported_media_type', 'This parser supports PDF and price-list CSV only.')
    if limits.max_pages < 1:
        raise ValueError('max_pages must be positive')
    # Explicitly own the stream, including failures while opening/enumerating the PDF.
    with Path(stored_file).open('rb') as stream:
        content_hash = sha256()
        while block := stream.read(64 * 1024):
            content_hash.update(block)
        stream.seek(0)
        try:
            pdf = pdfplumber.open(stream)
        except Exception as exc:
            if not _content_error(exc):
                raise
            raise ParseError('pdf_unreadable', 'Cannot open the PDF; it may be damaged or encrypted.') from None
        with pdf:
            try:
                pages = pdf.pages
            except Exception as exc:
                if not _content_error(exc):
                    raise
                raise ParseError('pdf_pages_unreadable', 'Cannot reliably enumerate PDF pages.') from None
            if len(pages) > limits.max_pages:
                raise ParseError('pdf_page_limit', 'PDF exceeds the page limit.')
            from .pdf_reading import READING_VERSION, reading_page
            evidence, results, warnings, reading_pages = [], [], [], []
            for number, page in enumerate(pages, 1):
                try:
                    if check is not None:
                        check()
                    text = (page.extract_text(layout=False) or '').strip()
                    if not text or not any(c.isalnum() for c in text):
                        reading_pages.append(reading_page(number, '', page.bbox, content_hash.hexdigest(), 'no_text'))
                        results.append(PageResult(number, 'no_text'))
                        warnings.append(ParseWarning(number, 'no_usable_text', 'No usable native text; page skipped.'))
                        continue
                    reading_pages.append(reading_page(number, text, page.bbox, content_hash.hexdigest()))
                    try:
                        regions, uncertain = group_page(page)
                    except Exception as exc:
                        if not _content_error(exc):
                            raise
                        regions, uncertain = (), True
                    if not regions:
                        regions = (Region((), (SourceSpan(text, tuple(page.bbox)),), 'fallback'),)
                        uncertain = True
                    reading_pages[-1]['structure'] = [
                        {'kind': region.kind,
                         'headings': [{'text': s.text, 'bbox': list(s.bbox)} for s in region.header],
                         'unit_count': len(region.units)} for region in regions]
                    reading_pages[-1]['layout_uncertain'] = uncertain
                    chunks, omitted = _page_evidence(regions, content_hash.hexdigest(), number)
                    evidence.extend(chunks)
                    if omitted:
                        uncertain = True
                        warnings.append(ParseWarning(number, 'oversized_unit_skipped', 'A source unit could not be safely split within the character budget; omitted.'))
                    if uncertain:
                        warnings.append(ParseWarning(number, 'layout_uncertain', 'Some text has uncertain layout; source regions retained without inferred relationships.'))
                    results.append(PageResult(number, 'failed' if not chunks else 'degraded' if uncertain else 'extracted'))
                except Exception as exc:
                    if not _content_error(exc):
                        raise
                    if not reading_pages or reading_pages[-1]['page_number'] != number:
                        reading_pages.append({'page_number': number, 'status': 'failed', 'units': []})
                    results.append(PageResult(number, 'failed'))
                    warnings.append(ParseWarning(number, 'page_parse_failed', 'Native text extraction failed; page skipped.'))
                finally:
                    page.close()
            if not evidence:
                # Preserve existing v2 retrieval identities whenever any valid
                # chunks exist. A wholly oversized native-text document instead
                # gets bounded page-text fallback evidence, never an empty index.
                for reading_page_result in reading_pages:
                    for unit in reading_page_result['units']:
                        locator = unit['locator']
                        evidence.append(Evidence(unit['evidence_id'], unit['text'],
                            locator['page_number'], tuple(locator['bbox']),
                            retrieval_text=unit['text'],
                            source_spans=(SourceSpan(unit['text'], tuple(locator['bbox'])),)))
                if evidence:
                    results = [PageResult(p.page_number, 'degraded') if p.status == 'failed'
                               and reading_pages[p.page_number - 1]['units'] else p for p in results]
                    warnings = [w for w in warnings if w.code != 'oversized_unit_skipped']
                    warnings.extend(ParseWarning(p['page_number'], 'native_reading_fallback',
                        'Oversized layout units use bounded native page text and page-level coordinates.')
                        for p in reading_pages if p['units'])
            if not evidence:
                raise ParseError('no_usable_evidence', 'No usable native-text evidence was extracted.', pages=results, warnings=warnings)
            reading = {'reading_version': READING_VERSION, 'content_hash': content_hash.hexdigest(), 'pages': reading_pages,
                       'warnings': [{'code': 'native_reading_order', 'message':
                           'Native page text uses page-level coordinates; layout relationships and reading order may be uncertain.'}]}
            return ParsedDocument(tuple(evidence), tuple(results), tuple(warnings), reading=reading)
