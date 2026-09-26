# M1 parsing evidence — 2026-09-26

## Scope and environment

M1 baseline: b8421e72fd70fb8f62eca93ea39ab4bca8de9690 plus this checkpoint's document changes. Reused the earlier 32-file PDF scan, CSV structural scan and visual reviews of procurement page 1, Rondel page 2, Highbay page 18 and scanned declaration page 1. Did not repeat full extraction, installation or M0 tests.

New checks used bundled analysis tools: pypdf 6.10.0 and pdfplumber 0.11.9. These are analysis environment versions, not project dependency selections. Source files are fixed by eval/material_manifest.json. New visual review: Lunis R page 4 for holdout annotation only. Existing PDF skill/Poppler render evidence remains in ignored tmp/m1; it is not required by the application.

## Simple parameter tables

Rondel page 2: pdfplumber page.extract_tables() returned five candidates, including two empty graphic-derived candidates. The order table has five rows/six columns with correct order number, temperature, luminous flux, wattage, control and weight; headers are absent. An accessory table has continuation cells represented as null. Therefore default table detection alone FAILS the complete labeled-fact requirement.

Highbay page 18: default extract_tables() returned four empty candidates and no useful parameter table. This is not a successful table extraction. The page's parameter blocks are nevertheless readable as labeled text.

For both pages, page.extract_text(layout=True) retains the development-case facts with headings and values. Rondel keeps the order-variant heading, two-line header and five order rows. Highbay keeps midi/maxi headings before their own dimensions, weight and temperature ranges, followed by the all-sizes group. These were compared to the previously inspected page images. Evidence supports a layout-aware text starting point for D04–D08, not general table reconstruction.

Known defects: Rondel's rotated dimension annotation appears as 82 instead of 28 in one layout area, although its labeled Dimensions row correctly says 28 mm; rotated footer text is reversed. Accessory continuation text and columns can still interleave. Highbay's shared rows contain nearby promotional text. Do not silently prefer an unlabeled graphic number over the labeled specification or claim automatic quality detection is solved.

Implementation target: preserve page text and coordinates/blocks while retaining the original page locator. Keep a model-specific parameter group together, and attach shared group headings and table headers when splitting. Do not flatten isolated numeric cells into independent chunks or hardcode SITECO model names. Use table extraction only where its labels and associations have been verified. A future M2 parser adapter must reproduce these facts through its public interface; M1 does not ship that adapter.

Minimal reproduction on the manifest's development PDFs only: open with pdfplumber, select pages[page_number - 1], compare extract_tables() and extract_text(layout=True) with the source page. No bespoke crop coordinates or per-file extraction rules were tuned. The chosen baseline is labeled/layout-aware text, not a promise of arbitrary PDF tables; final application library pinning and Linux behavior remain M2 work.

## CSV and question integrity

Reused 18-column / 11,386-record / unique-order-number structural result. Added direct checks of records 1, 2, 11385, 11386 and exact absence of NOT-A-SITECO-ORDER-000. Reserved records include thousands separators (2.075,10 and 2.513,30). Decimal interpretation must remove the locale's grouping separator before replacing its decimal separator; preserve the raw cell alongside a normalized value, and do not treat empty numeric cells as zero.

Validated 16 unique case IDs, document-scope membership of every evidence item, valid PDF page bounds and exact CSV record/order correspondence. Cases reference assistant-checked source facts, not LLM-generated application outputs. Procurement absence case D12 is limited to the selected terms; no Highbay match exists in the complete extracted text and no product-price evidence was found. It is not a claim about other uploaded files.

## Outcome

M1 material and parsing feasibility checkpoint is complete with explicit limitations. Simple labeled parameter groups and CSV exact lookup have enough evidence to begin implementation. Generic cell/table parsing is not passed, holdout application tests are not run, and no retrieval/answer/citation accuracy or Docker success is claimed. Final library choice, automatic quality checks and end-to-end verification remain implementation work.
