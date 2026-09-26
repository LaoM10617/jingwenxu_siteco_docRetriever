"""PDF parser contract tested with small, deterministic PDF fixtures."""
import pytest
from app.parsing import parse_document, ParseLimits, ParseError


def pdf_file(tmp_path, texts, *, commands=False):
    objects = [b'', b'']
    kids = []
    for text in texts:
        page_id = len(objects) + 1
        kids.append(f'{page_id} 0 R')
        content = (text if commands else f'BT /F1 12 Tf 20 100 Td ({text}) Tj ET').encode()
        objects.extend([
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> /F2 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> >> >> /Contents {page_id+1} 0 R >>'.encode(),
            b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream'])
    objects[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objects[1] = f'<< /Type /Pages /Count {len(texts)} /Kids [{" ".join(kids)}] >>'.encode()
    data = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
    start = len(data)
    data.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode())
    path = tmp_path / 'fixture.pdf'
    path.write_bytes(data)
    return path


def test_ruled_columns_keep_titles_and_parameters_separate(tmp_path):
    commands = []
    for x, title, value in [(10, 'Model A', 'Weight: 3 kg'), (110, 'Model B', 'Weight: 7 kg')]:
        commands.extend([f'BT /F1 8 Tf {x} 180 Td ({title}) Tj ET',
                         f'BT /F1 6 Tf {x} 160 Td ({value}) Tj ET',
                         f'BT /F1 6 Tf {x} 150 Td (Only at 25 C) Tj ET'])
        for y in (170, 155, 145):
            commands.append(f'{x} {y} m {x + 80} {y} l S')
    result = parse_document(pdf_file(tmp_path, ['\n'.join(commands)], commands=True), 'application/pdf', ParseLimits())
    a = next(e for e in result.evidence if '3 kg' in e.text)
    b = next(e for e in result.evidence if '7 kg' in e.text)
    assert 'Model A' in a.retrieval_text and 'Model B' not in a.retrieval_text
    assert 'Model B' in b.retrieval_text and 'Model A' not in b.retrieval_text
    assert 'Only at 25 C' in a.retrieval_text
    assert a.bbox[2] < b.bbox[0]


def test_long_table_chunks_repeat_original_header_and_keep_whole_rows(tmp_path):
    commands = ['BT /F1 2 Tf 10 198 Td (Model Z - power W at 25 C) Tj ET']
    for i in range(51):
        y = 193 - i * 3
        commands.append(f'10 {y} m 195 {y} l S')
        if i < 50:
            row = f'Row {i:02}: ' + 'rated power 25 W; only with supplied adapter. '
            commands.append(f'BT /F1 2 Tf 10 {y - 2} Td ({row}) Tj ET')
    path = pdf_file(tmp_path, ['\n'.join(commands)], commands=True)
    result = parse_document(path, 'application/pdf', ParseLimits())
    rows = [e for e in result.evidence if 'Row ' in e.text]
    assert len(rows) > 1
    assert all(len(e.retrieval_text) <= 6000 for e in rows)
    assert all('Model Z - power W at 25 C' in e.retrieval_text for e in rows)
    assert all(e.context and e.context[0].bbox[1] < e.source_spans[0].bbox[1] for e in rows)
    for i in range(50):
        matches = [e for e in rows if f'Row {i:02}:' in e.text]
        assert len(matches) == 1
        assert f'Row {i:02}: rated power 25 W; only with supplied adapter.' in matches[0].text
    assert result.evidence == parse_document(path, 'application/pdf', ParseLimits()).evidence


def test_numbered_clauses_keep_continuations_and_repeat_section(tmp_path):
    commands = ['BT /F2 2 Tf 10 198 Td (Article I: Conditions) Tj ET']
    for i in range(1, 21):
        y = 194 - i * 8
        commands.extend([f'BT /F1 2 Tf 10 {y} Td ({i}. Payment is due after delivery and approval of the goods; the supplier shall submit an invoice.) Tj ET',
                         f'BT /F1 2 Tf 10 {y-4} Td (Except when damage is reported; this condition remains part of the clause.) Tj ET'])
    result = parse_document(pdf_file(tmp_path, ['\n'.join(commands)], commands=True), 'application/pdf', ParseLimits())
    parts = [e for e in result.evidence if 'Payment' in e.text]
    assert len(parts) > 1
    assert all('Article I: Conditions' in e.retrieval_text for e in parts)
    for part in parts:
        assert part.text.count('Payment') == part.text.count('Except when')
        assert len(part.retrieval_text) <= 6000


def test_layout_content_failure_falls_back_once_to_native_text(tmp_path, monkeypatch):
    from pdfplumber.page import Page
    from pdfminer.psexceptions import PSSyntaxError
    calls = []
    def bad_edges(page):
        calls.append(page.page_number)
        raise PSSyntaxError('private-layout-detail')
    monkeypatch.setattr(Page, 'edges', property(bad_edges))
    result = parse_document(pdf_file(tmp_path, ['Still useful text']), 'application/pdf', ParseLimits())
    assert calls == [1]
    assert result.evidence[0].text == 'Still useful text'
    assert result.coverage['degraded'] == 1
    assert result.warnings[0].code == 'layout_uncertain'
    assert 'private-layout-detail' not in str(result)


def test_oversized_indivisible_unit_is_explicit_and_other_pages_survive(tmp_path):
    result = parse_document(pdf_file(tmp_path, ['A' * 6001, 'Useful']), 'application/pdf', ParseLimits())
    assert [e.page_number for e in result.evidence] == [2]
    assert result.pages[0].status == 'failed'
    assert any(w.code == 'oversized_unit_skipped' and w.page_number == 1 for w in result.warnings)


def test_generic_parameter_heading_retains_page_title_source(tmp_path):
    commands = 'BT /F1 16 Tf 10 190 Td (Product Q) Tj ET\nBT /F1 6 Tf 10 150 Td (Specifications) Tj ET\nBT /F1 6 Tf 10 130 Td (Power 9 W) Tj ET\nBT /F1 6 Tf 10 120 Td (Only at 25 C) Tj ET\n10 140 m 150 140 l S\n10 125 m 150 125 l S\n10 115 m 150 115 l S'
    result = parse_document(pdf_file(tmp_path, [commands], commands=True), 'application/pdf', ParseLimits())
    spec = next(e for e in result.evidence if 'Power 9 W' in e.text)
    assert 'Product Q' in spec.retrieval_text
    assert any(c.text == 'Product Q' and c.bbox[1] < 20 for c in spec.context)


def test_skip_empty_page_preserves_physical_pages_and_short_text(tmp_path):
    path = pdf_file(tmp_path, ['First clause', '', 'X1'])
    result = parse_document(path, 'application/pdf', ParseLimits())
    assert [e.page_number for e in result.evidence] == [1, 3]
    assert result.evidence[1].text == 'X1'
    assert [p.status for p in result.pages] == ['extracted', 'no_text', 'extracted']
    assert result.coverage == {'extracted': 2, 'degraded': 0, 'no_text': 1, 'failed': 0}
    assert result.warnings[0].page_number == 2
    assert result.evidence == parse_document(path, 'application/pdf', ParseLimits()).evidence


def test_empty_and_unreadable_pdf_fail_explicitly(tmp_path):
    with pytest.raises(ParseError) as error:
        parse_document(pdf_file(tmp_path, ['', '']), 'application/pdf', ParseLimits())
    assert error.value.code == 'no_usable_evidence'
    assert len(error.value.pages) == 2
    path = tmp_path / 'broken.pdf'
    path.write_bytes(b'not a PDF')
    with pytest.raises(ParseError) as error:
        parse_document(path, 'application/pdf', ParseLimits())
    assert error.value.code == 'pdf_unreadable'
    assert str(path) not in str(error.value)


def test_fifty_page_boundary(tmp_path):
    assert parse_document(pdf_file(tmp_path, ['X'] * 50), 'application/pdf', ParseLimits()).page_count == 50
    with pytest.raises(ParseError) as error:
        parse_document(pdf_file(tmp_path, ['X'] * 51), 'application/pdf', ParseLimits())
    assert error.value.code == 'pdf_page_limit'


def test_page_content_failure_isolated(tmp_path, monkeypatch):
    from pdfplumber.page import Page
    from pdfminer.psexceptions import PSSyntaxError
    original = Page.extract_text
    def extract(page, *args, **kwargs):
        if page.page_number == 2:
            raise PSSyntaxError('private-parser-detail')
        return original(page, *args, **kwargs)
    monkeypatch.setattr(Page, 'extract_text', extract)
    result = parse_document(pdf_file(tmp_path, ['A', 'B', 'C']), 'application/pdf', ParseLimits())
    assert [e.page_number for e in result.evidence] == [1, 3]
    assert result.coverage['failed'] == 1
    assert result.warnings[0].page_number == 2
    assert 'private-parser-detail' not in str(result)


@pytest.mark.parametrize('cause', [OSError('disk'), RuntimeError('bug')])
def test_non_content_errors_are_not_page_warnings(tmp_path, monkeypatch, cause):
    from pdfplumber.page import Page
    from pdfplumber.utils.exceptions import PdfminerException
    def extract(*args, **kwargs):
        raise PdfminerException(cause) from cause
    monkeypatch.setattr(Page, 'extract_text', extract)
    with pytest.raises(PdfminerException):
        parse_document(pdf_file(tmp_path, ['A']), 'application/pdf', ParseLimits())
