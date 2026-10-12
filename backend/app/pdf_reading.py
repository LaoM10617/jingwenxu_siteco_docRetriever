"""Complete native page text, independent of retrieval chunk selection.

Coordinates intentionally describe the page: native extraction establishes text
order, not reliable paragraph or table relationships. OCR can supply a separate
versioned representation later, without changing this native-text contract.
"""
from hashlib import sha256
import pdfplumber

READING_VERSION = 'native-pages-v1/pdfplumber-' + pdfplumber.__version__
UNIT_MAX = 6000


def reading_page(number, text, bbox, content_hash, status='extracted'):
    units = []
    for offset in range(0, len(text), UNIT_MAX):
        part = text[offset:offset + UNIT_MAX]
        identity = sha256(f'{content_hash}\0{READING_VERSION}\0{number}\0{offset}\0{part}'.encode()).hexdigest()
        units.append({'evidence_id': 'reading:' + identity, 'text': part,
                      'locator': {'kind': 'pdf', 'page_number': number, 'bbox': list(bbox)},
                      'source_spans': [{'text': part, 'bbox': list(bbox)}],
                      'context': [], 'section': None, 'continuation': offset > 0})
    return {'page_number': number, 'status': status, 'units': units}
