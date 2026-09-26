# M2.5 CSV contract

2026-09-26. Approved scope: P-025 and the user's sequential authorization of
steps 1–3 and 4–6. Parsing, durable publication and exact lookup are implemented.

## Input and source records

- UTF-8 (optional initial BOM), semicolon delimiter, double-quoted fields and
  doubled quotes. Open with `newline=''` and use the standard-library CSV reader
  in strict mode. No delimiter/encoding guessing or spreadsheet formulas.
- The price-list schema has these 18 ordered headers: Bestellnummer, EAN,
  Kurzbezeichnung, Listenpreis, gültig ab, Rabattgruppe, Familie, Leuchtenart,
  Rastertyp, Reflektortyp, Abdeckungstyp, Lichtaustritt, Blendbegrenzung,
  Vorschaltgeraeteart, Lampenanzahl, Lampentyp, Lampenleistung, Schutzart.
  This is a schema restriction, not a filename/hash/order-number restriction.
- Exact header/order required. Missing/duplicate/unknown columns, incorrect row
  width, invalid encoding/CSV quoting, header-only files and record overflow
  fail the whole parse. No partial result is returned after a structural error.
- At most 20,000 logical data records (header excluded). Empty physical lines
  outside quoted fields are ignored; a row of 18 empty fields is a record.
  A quoted field containing newlines remains within one record. The standard
  reader field-size limit also applies; oversized fields fail explicitly.
- Preserve ordered headers and every decoded raw cell, including whitespace,
  quotes inside values and empty strings. CSV quoting syntax is not cell content;
  the retained original file preserves the exact bytes. Record numbers start at 1.
- CSV results have records/headers and record-specific warnings, not PDF pages or
  bounding boxes. Each record has a stable evidence ID bound to file hash, parser
  version and record number, and `locator={kind: csv, record_number: N}`.
  Upload document_id is attached by the ingestion adapter.
- `order_id` is the original Bestellnummer with only outer whitespace stripped.
  Preserve leading zeros, case, inner whitespace and punctuation. Changed keys
  receive a warning; missing keys remain as records with a warning and cannot be
  looked up by order. EAN and all other fields remain strings. Duplicate keys
  remain separate records with distinct evidence IDs; issue a duplicate warning.

## Price

Keep the original Listenpreis cell. `price_status` is valid/missing/invalid;
`price` is a Decimal only for valid values, otherwise None.

After trimming outer whitespace, accept an optional sign, ASCII integer digits
(ungrouped or with correctly placed groups of three separated by dots), and an
optional comma followed by decimal digits. For example, synthetic `1.234,50`
becomes Decimal('1234.50'). Do not accept decimal dots, malformed grouping,
currency text, scientific notation, NaN or Infinity. Do not round or infer
currency, tax, discount or scale. Empty/whitespace-only prices are missing, not
zero. Invalid prices retain their raw value and a warning; valid records can
still be returned later, but invalid/missing prices cannot enter numeric
comparisons as zero. The UI must expose these warnings independently of the LLM.

## Interfaces and acceptance

T-003 (existing): `parse_document(path, 'text/csv', ParseLimits(max_records=...))`
returns ParsedCsvDocument or a fixed ParseError. PDF behavior stays unchanged.
Tests use real synthetic files through this interface: quoted semicolons/newlines,
raw strings/leading zeros, stable IDs, duplicates, blanks, malformed structures,
limits and Decimal edge cases. Filesystem errors propagate as filesystem errors.

T-006 (implemented as DocumentService.lookup_orders):
`lookup_orders(order_ids, document_ids, offset=0, limit=50)`.
Both lists must be explicit/nonempty; order IDs must be strings. Trim outer
whitespace, reject empty keys, and deduplicate repeated query keys while retaining
their first-request order. No numeric coercion, case folding, prefix/fuzzy matching
or fallback to all documents. Validate all selected IDs: missing/not-ready/non-CSV
is an explicit error, never silently drop documents. Use parameterized SQL.

Return actual document scope, per-order counts, unmatched orders, total record
count, current-page records and whether more exist. Count against the full match
set before pagination. Retain all duplicate sources; stable order is requested
order position, document ID, record number. Each row carries source identity,
ordered original columns/values and price status. Test scope isolation, leading
zeros, duplicates, multiple orders, missing IDs, invalid inputs and paging.
The production API has no new query route or chat UI in M2.5. The acceptance-only
adapter in eval/m25_acceptance_app.py calls this method inside the owning backend
process and is mounted only for acceptance, never included in runtime images.

Query offset is a nonnegative integer and limit is an integer from 1 to 100;
booleans and numeric order IDs are rejected. The result has document_ids,
order_ids (deduplicated), counts=[{order_id,count}], unmatched_order_ids, total,
offset, limit, has_more and records. A result row has document_id,
original_filename, evidence_id, order_id, locator, headers, raw_values, text,
price_status and price. Across uploads, identify a source by document_id plus
evidence_id; identical bytes can have the same evidence_id in different uploads.
Errors are invalid_query/invalid_pagination (422), document_not_found (404),
document_not_ready (409) or document_not_csv (422). Validate the whole scope
before searching; an invalid selected document does not yield partial matches.

## Persistence and publication

SQLite stores ordered records in csv_records with a (document_id, order_id)
binary-collation index; no pandas or vector/model call is involved. Decimal
values are stored and returned as lossless decimal strings, never REAL/float.
The original numeric cell remains independently available in raw_values.

Stage all rows and metadata in one transaction while the document is processing.
Validate counts, contiguous record positions, schema/version, content digest and
summary, then change to ready under the lifecycle lock. Only published documents
can be read. On restart validate the durable snapshot before serving; do not
reparse or call a model. Missing/corrupt snapshots fail index_restore_failed.
Retry clears previous rows, metadata, summary and artifacts before rebuilding;
interrupted work never automatically resumes or exposes staged records.

Mixed missing-key records stay in evidence and warnings but cannot match an order.
A file with no nonempty order IDs fails csv_no_order_ids, retaining its summary
and warnings; it does not become a misleading ready document. No raw failed-file
record preview is opened before ready. Structural failures remain whole-file failures.

CSV document status returns parsing.kind=csv, parser_version, record_count,
indexed_record_count and price_counts(valid/missing/invalid), plus record-specific
warnings. Polling does not load all records. Evidence pages expose ordered headers,
raw_values, price and price_status in addition to text and the CSV locator.
No PDF page/coverage fields are manufactured for CSV.

Large results will expose total count and all records via pagination, separately
from the model context budget. Do not claim a summary of all results when the
model saw only one page. Filtering/aggregation are not added by this contract.

## Development material and limitations

Full-file parsing/count acceptance uses the manifest price CSV, but only records
1 and 2 are used for semantic development checks. Reserved rows are ingested as
ordinary data without displaying their values or using them to change rules.
Synthetic fixtures establish thousands/decimal and malformed-value behavior.
Do not load holdout question answers for this work.

Record observed deficiencies separately from unimplemented query behavior.
Exact matching deliberately does not repair case/inner-space/punctuation errors;
changing that policy later requires evidence of user need and collision checks.
