"""CSV parsing acceptance through the existing T-003 interface."""
import csv
from decimal import Decimal
import pytest

from app.parsing import parse_document, ParseLimits, ParseError


HEADERS = ('Bestellnummer', 'EAN', 'Kurzbezeichnung', 'Listenpreis', 'gültig ab',
           'Rabattgruppe', 'Familie', 'Leuchtenart', 'Rastertyp', 'Reflektortyp',
           'Abdeckungstyp', 'Lichtaustritt', 'Blendbegrenzung', 'Vorschaltgeraeteart',
           'Lampenanzahl', 'Lampentyp', 'Lampenleistung', 'Schutzart')


def row(order='001Ab-9', price='123,40'):
    return [order, '0001234567890', 'Fixture', price, '01.06.2026'] + [''] * 13


def csv_file(tmp_path, rows, headers=HEADERS):
    path = tmp_path / 'any-name.csv'
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def test_csv_preserves_raw_fields_and_logical_record_sources(tmp_path):
    first = row()
    first[2] = 'Description; with "quotes"\nand a continuation'
    path = csv_file(tmp_path, [first, row('second')])
    result = parse_document(path, 'text/csv', ParseLimits())
    assert result.headers == HEADERS
    assert result.record_count == 2
    assert result.records[0].raw_values == tuple(first)
    assert result.records[0].order_id == '001Ab-9'
    assert result.records[0].price == Decimal('123.40')
    assert result.records[0].price_status == 'valid'
    assert [r.locator for r in result.records] == [
        {'kind': 'csv', 'record_number': 1}, {'kind': 'csv', 'record_number': 2}]
    assert len({r.evidence_id for r in result.records}) == 2
    assert result == parse_document(path, 'text/csv', ParseLimits())


@pytest.mark.parametrize('headers', [('', 'name'), ('name', 'name'), ('  ', 'name')])
def test_csv_rejects_empty_or_duplicate_headers(tmp_path, headers):
    with pytest.raises(ParseError) as error:
        parse_document(csv_file(tmp_path, [['a', 'b']], headers), 'text/csv', ParseLimits())
    assert error.value.code == 'csv_header_invalid'


@pytest.mark.parametrize('delimiter', [',', ';', '\t'])
@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'utf-16'])
def test_generic_csv_preserves_strings(tmp_path, delimiter, encoding):
    path = tmp_path / 'generic.csv'
    with path.open('w', encoding=encoding, newline='') as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerow(['identifier', 'value', 'note'])
        writer.writerow(['0001', 'NA', 'a; b, c\ncontinued'])
    parsed = parse_document(path, 'text/csv', ParseLimits())
    assert parsed.headers == ('identifier', 'value', 'note')
    assert parsed.records[0].raw_values == ('0001', 'NA', 'a; b, c\ncontinued')
    assert parsed.warnings == ()


@pytest.mark.parametrize('values', [row()[:-1], row() + ['extra']])
def test_csv_fails_whole_document_on_wrong_record_width(tmp_path, values):
    with pytest.raises(ParseError) as error:
        parse_document(csv_file(tmp_path, [row(), values]), 'text/csv', ParseLimits())
    assert error.value.code == 'csv_record_invalid'


@pytest.mark.parametrize('body,code', [(b'', 'csv_header_invalid'),
                                    (b'\xff', 'csv_encoding_invalid'),
                                    (b'"unfinished', 'csv_unreadable')])
def test_csv_reports_fixed_content_errors(tmp_path, body, code):
    path = tmp_path / 'invalid.csv'
    path.write_bytes(body)
    with pytest.raises(ParseError) as error:
        parse_document(path, 'text/csv', ParseLimits())
    assert error.value.code == code


def test_csv_requires_records_and_honors_twenty_thousand_limit(tmp_path):
    with pytest.raises(ParseError) as error:
        parse_document(csv_file(tmp_path, []), 'text/csv', ParseLimits())
    assert error.value.code == 'csv_no_records'
    path = csv_file(tmp_path, (row(str(i)) for i in range(20_000)))
    assert parse_document(path, 'text/csv', ParseLimits()).record_count == 20_000
    with path.open('a', encoding='utf-8', newline='') as stream:
        csv.writer(stream, delimiter=';').writerow(row('overflow'))
    with pytest.raises(ParseError) as error:
        parse_document(path, 'text/csv', ParseLimits())
    assert error.value.code == 'csv_record_limit'


def test_csv_bom_blank_lines_and_multiline_records(tmp_path):
    path = csv_file(tmp_path, [row('first'), row('second')])
    body = path.read_bytes()
    path.write_bytes(b'\xef\xbb\xbf' + body.replace(b'\r\n', b'\r\n\r\n'))
    result = parse_document(path, 'text/csv', ParseLimits())
    assert result.headers == HEADERS
    assert [r.record_number for r in result.records] == [1, 2]


def test_csv_does_not_hide_filesystem_errors_or_accept_invalid_limits(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_document(tmp_path / 'missing.csv', 'text/csv', ParseLimits())
    with pytest.raises(ValueError):
        parse_document(csv_file(tmp_path, [row()]), 'text/csv', ParseLimits(max_records=0))


@pytest.mark.parametrize('raw,status,expected', [
    ('1.234,50', 'valid', '1234.50'), ('12.345.678,901', 'valid', '12345678.901'),
    ('0', 'valid', '0'), ('0,00', 'valid', '0.00'), ('-12,50', 'valid', '-12.50'),
    (' +0012,30 ', 'valid', '12.30'), ('1234', 'valid', '1234'),
    ('1.234', 'valid', '1234'), ('0,12345678901234567890123456789', 'valid', '0.12345678901234567890123456789'),
    ('', 'missing', None), ('  ', 'missing', None),
    ('12.34', 'invalid', None), ('1,234.50', 'invalid', None),
    ('1.23,40', 'invalid', None), ('12,', 'invalid', None),
    ('NaN', 'invalid', None), ('Infinity', 'invalid', None),
    ('1e3', 'invalid', None), ('€12,50', 'invalid', None),
    ('1 234,50', 'invalid', None), ('１２,５０', 'invalid', None),
])
def test_csv_price_classification_preserves_raw_values(tmp_path, raw, status, expected):
    result = parse_document(csv_file(tmp_path, [row(price=raw)]), 'text/csv', ParseLimits())
    record = result.records[0]
    assert record.raw_values[3] == raw
    assert record.price_status == status
    assert record.price == (Decimal(expected) if expected is not None else None)
    if status == 'valid':
        assert result.warnings == ()
    else:
        assert [(w.record_number, w.column, w.code) for w in result.warnings] == [
            (1, 'Listenpreis', f'price_{status}')]


def test_csv_missing_keys_duplicates_and_trim_collisions_remain_traceable(tmp_path):
    records = [row(' 001Ab-9 '), row('001Ab-9'), row('001ab-9'), row('001Ab -9'),
               row('001Ab-9'), row(' ', ''), [''] * 18]
    result = parse_document(csv_file(tmp_path, records), 'text/csv', ParseLimits())
    assert [r.order_id for r in result.records] == ['001Ab-9', '001Ab-9', '001ab-9', '001Ab -9', '001Ab-9', '', '']
    assert [r.raw_values for r in result.records] == [tuple(r) for r in records]
    assert len({r.evidence_id for r in result.records}) == 7
    assert {(w.record_number, w.code) for w in result.warnings} == {
        (1, 'order_id_trimmed'), (2, 'duplicate_order_id'), (5, 'duplicate_order_id'),
        (6, 'order_id_missing'), (6, 'price_missing'), (7, 'order_id_missing'), (7, 'price_missing')}


def test_csv_changed_bytes_get_new_evidence_identity(tmp_path):
    path = csv_file(tmp_path, [row()])
    before = parse_document(path, 'text/csv', ParseLimits())
    csv_file(tmp_path, [row(price='123,41')])
    after = parse_document(path, 'text/csv', ParseLimits())
    assert before.records[0].evidence_id != after.records[0].evidence_id


def test_csv_late_structure_failure_and_oversized_field_return_no_partial_result(tmp_path):
    path = csv_file(tmp_path, [row()])
    with path.open('a', encoding='utf-8') as stream:
        stream.write('"unfinished')
    with pytest.raises(ParseError) as error:
        parse_document(path, 'text/csv', ParseLimits())
    assert error.value.code == 'csv_unreadable'
    values = row()
    values[2] = 'x' * (csv.field_size_limit() + 1)
    with pytest.raises(ParseError) as error:
        parse_document(csv_file(tmp_path, [values]), 'text/csv', ParseLimits())
    assert error.value.code == 'csv_unreadable'


def test_reordered_siteco_columns_keep_exact_semantics(tmp_path):
    headers = tuple(reversed(HEADERS))
    values = tuple(reversed(row(' 001 ', '2.345,60')))
    parsed = parse_document(csv_file(tmp_path, [values], headers), 'text/csv', ParseLimits())
    assert parsed.records[0].order_id == '001'
    assert parsed.records[0].price == Decimal('2345.60')
    assert parsed.records[0].raw_values == values


@pytest.mark.parametrize('raw,status,warning', [('1.234', 'invalid', 'price_unconfirmed'),
                                               ('', 'missing', 'price_missing')])
def test_generic_price_column_never_assumes_german_amounts(tmp_path, raw, status, warning):
    parsed = parse_document(csv_file(tmp_path, [['001', raw]],
                                    ('Bestellnummer', 'Listenpreis')), 'text/csv', ParseLimits())
    assert parsed.records[0].price is None
    assert parsed.records[0].price_status == status
    assert parsed.records[0].raw_values == ('001', raw)
    assert [w.code for w in parsed.warnings] == [warning]


def test_quoted_header_delimiter_is_preserved(tmp_path):
    parsed = parse_document(csv_file(tmp_path, [['0001', 'NA']],
                                    ('identifier;external', 'marker')), 'text/csv', ParseLimits())
    assert parsed.headers == ('identifier;external', 'marker')


def test_ambiguous_header_delimiters_require_clarification(tmp_path):
    path = tmp_path / 'ambiguous.csv'
    path.write_text('a,b;c\n1,2;3\n', encoding='utf-8')
    with pytest.raises(ParseError) as error:
        parse_document(path, 'text/csv', ParseLimits())
    assert error.value.code == 'csv_dialect_ambiguous'
