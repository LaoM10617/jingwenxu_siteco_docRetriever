"""Full CSV structural acceptance; only records 1/2 receive semantic checks.

No held-out questions or row values are loaded as reference answers or printed.
Run with the project Python; optionally provide the CSV path for a container.
"""
import csv
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.parsing import parse_document, ParseLimits


def check(path):
    assert sha256(path.read_bytes()).hexdigest() == 'b58bcea0e2d5c1e9f0017a25d3f1153bf75c25c0e78dd02a9a711ceb699483b9', 'Material differs from the fixed M1 manifest.'
    start = perf_counter()
    result = parse_document(path, 'text/csv', ParseLimits())
    elapsed = perf_counter() - start
    assert result.record_count == 11386
    assert len(result.headers) == 18
    assert len({r.evidence_id for r in result.records}) == result.record_count
    # Structural integrity over the full file, not semantic holdout evaluation.
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream, delimiter=';')
        assert tuple(next(reader)) == result.headers
        originals = (values for values in reader if values)
        for number, (original, record) in enumerate(zip(originals, result.records, strict=True), 1):
            assert record.raw_values == tuple(original)
            assert record.record_number == number
    for record, order, ean in zip(result.records[:2],
                                  ('51DB11EC11B1D', '51DB11EC11D1D'),
                                  ('4069025783196', '4069025783219')):
        assert record.order_id == order
        assert record.raw_values[1] == ean
        assert record.raw_values[3:5] == ('183,20', '01.06.2026')
        assert record.price_status == 'valid' and record.price == Decimal('183.20')
    assert result == parse_document(path, 'text/csv', ParseLimits())
    return {
        'parser_version': result.parser_version,
        'records': result.record_count, 'columns': len(result.headers),
        'raw_values_and_logical_positions': 'preserved for all records',
        'stable_unique_evidence_ids': True,
        'semantic_checks': 'development records 1 and 2 only',
        'warnings': len(result.warnings),
        'parse_seconds': round(elapsed, 4),
        'lookup_and_ready_acceptance': 'separate lifecycle/browser tests; this checker covers parsing only',
    }


if __name__ == '__main__':
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'data/Price Lists/leuchten_siteco_LPR_2026_06.csv'
    print(json.dumps(check(path), indent=2))
