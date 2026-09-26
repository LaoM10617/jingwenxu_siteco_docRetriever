"""The explicitly supported price-list schema; no inference or model calls."""
import csv
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from io import TextIOWrapper
from pathlib import Path
import re
from typing import Literal

CSV_PARSER_VERSION = 'price-list-v1'
PRICE_PATTERN = re.compile(r'[+-]?(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,[0-9]+)?')
HEADERS = ('Bestellnummer', 'EAN', 'Kurzbezeichnung', 'Listenpreis', 'gültig ab',
           'Rabattgruppe', 'Familie', 'Leuchtenart', 'Rastertyp', 'Reflektortyp',
           'Abdeckungstyp', 'Lichtaustritt', 'Blendbegrenzung', 'Vorschaltgeraeteart',
           'Lampenanzahl', 'Lampentyp', 'Lampenleistung', 'Schutzart')


@dataclass(frozen=True)
class CsvWarning:
    record_number: int
    column: str
    code: str
    message: str


@dataclass(frozen=True)
class CsvRecord:
    evidence_id: str
    record_number: int
    raw_values: tuple[str, ...]
    order_id: str
    price_status: Literal['valid', 'missing', 'invalid']
    price: Decimal | None

    @property
    def locator(self):
        return {'kind': 'csv', 'record_number': self.record_number}


@dataclass(frozen=True)
class ParsedCsvDocument:
    headers: tuple[str, ...]
    records: tuple[CsvRecord, ...]
    warnings: tuple[CsvWarning, ...]
    parser_version: str = CSV_PARSER_VERSION

    @property
    def record_count(self):
        return len(self.records)


def _price(raw):
    value = raw.strip()
    if not value:
        return 'missing', None
    if not PRICE_PATTERN.fullmatch(value):
        return 'invalid', None
    return 'valid', Decimal(value.replace('.', '').replace(',', '.'))


def parse_csv(stored_file: Path, max_records: int) -> ParsedCsvDocument:
    from .parsing import ParseError
    if max_records < 1:
        raise ValueError('max_records must be positive')
    with Path(stored_file).open('rb') as binary:
        digest = sha256()
        while block := binary.read(64 * 1024):
            digest.update(block)
        binary.seek(0)
        with TextIOWrapper(binary, encoding='utf-8-sig', newline='') as stream:
            try:
                reader = csv.reader(stream, delimiter=';', strict=True)
                headers = tuple(next(reader, ()))
                if headers != HEADERS:
                    raise ParseError('csv_header_invalid', 'CSV requires the supported price-list headers in order.')
                records, warnings, seen_orders = [], [], set()
                for values in reader:
                    if not values:
                        continue
                    number = len(records) + 1
                    if number > max_records:
                        raise ParseError('csv_record_limit', 'CSV exceeds the data record limit.')
                    if len(values) != len(headers):
                        raise ParseError('csv_record_invalid', 'CSV record has the wrong number of fields.')
                    identity = sha256(f'{digest.hexdigest()}\0{CSV_PARSER_VERSION}\0{number}'.encode()).hexdigest()
                    order_id = values[0].strip()
                    if not order_id:
                        warnings.append(CsvWarning(number, 'Bestellnummer', 'order_id_missing',
                                                   'Order ID is missing; record retained but not searchable by order.'))
                    else:
                        if order_id != values[0]:
                            warnings.append(CsvWarning(number, 'Bestellnummer', 'order_id_trimmed',
                                                       'Outer whitespace removed from the match key; original value retained.'))
                        if order_id in seen_orders:
                            warnings.append(CsvWarning(number, 'Bestellnummer', 'duplicate_order_id',
                                                       'Order ID repeats an earlier record; all sources retained.'))
                        seen_orders.add(order_id)
                    price_status, price = _price(values[3])
                    if price_status != 'valid':
                        warnings.append(CsvWarning(number, 'Listenpreis', f'price_{price_status}',
                                                   'Price is missing or invalid; original value retained, no numeric price available.'))
                    records.append(CsvRecord(identity, number, tuple(values), order_id, price_status, price))
                if not records:
                    raise ParseError('csv_no_records', 'CSV contains no data records.')
            except UnicodeDecodeError:
                raise ParseError('csv_encoding_invalid', 'CSV must be valid UTF-8.') from None
            except csv.Error:
                raise ParseError('csv_unreadable', 'CSV quoting is invalid or a field exceeds the reader limit.') from None
    return ParsedCsvDocument(headers, tuple(records), tuple(warnings))
