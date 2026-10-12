"""Fixed trusted phase-A workload; no natural-language code generation."""
import csv
from hashlib import sha256
import json
from pathlib import Path
import time


started = time.monotonic()
source = Path('/inputs/data.csv')
digest = sha256(source.read_bytes()).hexdigest()
with source.open(encoding='utf-8-sig', newline='') as stream:
    reader = csv.DictReader(stream, delimiter=';')
    rows = list(reader)
loaded = time.monotonic()
total_cents, priced_rows = 0, 0
for row in rows:
    raw = row['Listenpreis'].strip()
    if not raw:
        continue
    whole, fractional = raw.replace('.', '').split(',')
    if len(fractional) != 2 or not whole.isdigit() or not fractional.isdigit():
        raise ValueError('Fixed probe requires nonnegative prices with two decimal places')
    total_cents += int(whole) * 100 + int(fractional)
    priced_rows += 1
computed = time.monotonic()
result = {
    'kind': 'table',
    'columns': ['row_count', 'priced_rows', 'missing_prices', 'price_sum'],
    'rows': [[len(rows), priced_rows, len(rows) - priced_rows,
              f'{total_cents // 100}.{total_cents % 100:02d}']],
    'source_sha256': digest,
    'scope': 'all data records; no deduplication; missing prices excluded from sum',
    'unit': 'source price unit; currency not declared by CSV',
    'seconds': {'load': loaded - started, 'compute': computed - loaded},
}
encoded = json.dumps(result, allow_nan=False)
result['seconds']['encode'] = time.monotonic() - computed
print(json.dumps(result, allow_nan=False))
