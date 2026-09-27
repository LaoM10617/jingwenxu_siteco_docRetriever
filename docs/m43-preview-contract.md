# M4.3 source preview contract

Status: confirmed by the user, P-033. 2026-09-27.
Baseline main de8487dd25ce5f21127d59395e965686f0005a42; inherited changes retained.

## Minimal interface

GET /api/documents/{document_id}/evidence/{evidence_id}/preview returns a current,
server-resolved source preview. Accept identifiers only, never filesystem paths or
client-supplied coordinates. Reuse the existing ready/evidence identity gate:
unknown document/evidence 404, non-ready 409; missing original/render failure returns
an explicit preview error without removing the existing textual citation.

PDF response: original page PNG (bounded resolution, inline data URL), page number,
image dimensions, normalized evidence/context rectangles and positioning notice.
Render locally with the already locked pdfplumber/PDFium/Pillow stack. No new viewer,
CDN, model call or dependency. Serialize renderer access and bound image dimensions.
Use authoritative source_spans/context, not model-generated positions. Validate page
geometry, rotation, crop and coordinate ranges; unsupported geometry gives page-only
preview with a clear limitation, never a guessed bounding box. The UI can zoom the
same image and overlay together; high resolution beyond the raster is not promised.

CSV response: authoritative logical record number, ordered headers and raw values.
Current citations identify entire records, not individual model-cited fields. Highlight
the cited record and visibly label each original field; do not infer which fields a
sentence used. Field-level semantic attribution would require a separate answer contract.

The interface remains a single-user local demo. Do not expose original file downloads,
arbitrary pages/paths, authentication or a public file server. Old references resolve
only if their document/evidence still exists and is ready; otherwise show unavailability
while retaining frozen citation text. Preview never regenerates the answer.

## Confirmed test seams and acceptance

1. Document preview HTTP using isolated storage and controlled ingestion: PDF page and
   source/context regions, CSV multiline logical record, unknown/stale/non-ready IDs,
   missing original and bounded rendering. No access to running SQLite.
2. The same HTTP seam with synthetic known-position PDFs: different page sizes,
   nonzero origins/crop, 90-degree rotation and multiple regions. Check known positions
   against rendered pixels, not against a duplicate implementation formula.
3. Browser: click a citation, zoom, desktop/mobile layout, CSV raw fields, old-reference
   error and textual fallback. Replay existing real D01/D06 citations through GET only;
   visually inspect original pages and evidence/context overlays. No new live questions.

This is source-region highlighting, not proof that answer prose is semantically correct.
Any geometry fallback is recorded separately from successful highlighting acceptance.


## Implemented response and limits

PDF JSON: kind=pdf, page_number, width, height, image (PNG data URL), regions
({role: evidence|context, box: [left, top, width, height]} normalized to the visible
image), and notice (null or positioning limitation). CSV JSON: kind=csv,
record_number, headers, raw_values. Responses use Cache-Control: no-store.

Rendering is capped at 144 dpi and a 1,600-pixel long edge. Oversized/invalid pages
or renderer failures return preview_unavailable (503); an invalid source page number
returns 422. Missing originals return original_unavailable (404), and a changed
original hash returns original_changed (409). A preview failure does not change the
document's processing state. An unreadable original uses the existing storage error.
Coordinates outside the visible crop or absent coordinates produce no overlays and
a notice; an unrenderable page produces an error, not a fabricated preview.

The frontend rechecks on every explicit opening/retry, clears a previously displayed
preview before fetching and retains frozen citation text. It does not continuously
poll an already open preview. Source identities and original bytes are checked on the
backend; no client coordinates or paths are accepted. CSV raw fields are the published
parser record, not a newly generated answer. Verification: [M4.3 checkpoint](../eval/results/m43_preview.md).
