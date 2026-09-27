# M4.3 source preview checkpoint

2026-09-27. Implemented under user-confirmed P-033 and
[the preview contract](../../docs/m43-preview-contract.md).
Base main: de8487dd25ce5f21127d59395e965686f0005a42. Changes remain uncommitted;
inherited M4 documentation and M4.2 changes were preserved.

## Implemented

GET /api/documents/{document_id}/evidence/{evidence_id}/preview resolves a ready,
current source identity. PDF previews use the original file, verify its stored hash,
render locally with the existing locked PDF stack, and return normalized evidence
and context regions. No new runtime dependency, external viewer or model request.
Rendering is serialized, up to 144 dpi with a 1,600-pixel long edge. CSV returns the
published logical record's ordered original fields; the citation remains record-level.

The citation UI expands to an original-page image with distinct evidence/context
outlines, 100–300% zoom and Fit page. Every explicit opening rechecks availability.
Failed or stale previews retain frozen source text; unreliable coordinates show a
page-only notice. CSV shows all labelled raw fields, retaining leading zeroes, line
breaks and empty values. No inferred currency or sentence-to-field attribution.

## Verification and discovered failures

- Windows related preview/document HTTP/parsing/memory suite: 54 passed (12.42 s),
  including 17 preview checks. Final preview subset after test fixture cleanup:
  17 passed (4.85 s).
- Linux preview suite: 17 passed (5.44 s) in the existing test image, with current
  source/tests mounted read-only, network disabled and isolated temporary storage.
- TypeScript/Vite and Docker builds passed. Full browser suite on rebuilt Docker:
  32 passed, 12 opt-in skipped (30.2 s). After the final reopening fix, all 3 preview
  browser cases passed again (2.2 s); the complete suite was not repeated afterward.
- TDD first exposed missing CSV/PDF endpoints and missing UI. Geometry tests then
  exposed an incorrect box for nonzero MediaBox origin + CropBox + 90-degree rotation.
  Fixed the crop origin transformation relative to MediaBox; pixel-based checks pass
  for 0/90/180/270 rotations, changed page sizes, cropping, nonzero origin and combined
  cases. Tests compare source regions against actual rendered glyph pixels.
- Final inspection exposed cached previews surviving source withdrawal after closing
  and reopening. A browser regression failed first, then passed after rechecking on
  every opening and clearing the previous preview before the request.
- Multi-region/context tests, multiline CSV records, unknown/stale/non-ready identities,
  missing/changed originals, missing/out-of-view coordinates, invalid pages and image
  size limits pass. Page-only fallback is tested separately from successful highlighting.

## Real source checks (GET only)

Replayed retained task results with zero write requests and zero page errors:

- D01, M41-01: original physical page 1, four evidence regions plus one heading/context.
  The displayed Article II clauses include the Incoterms 2020 condition.
- D06, M41-04: original physical page 2, five table-row regions plus two title/header
  regions. The Rondel variants remain visibly aligned with their order numbers and units.
- D09, retained M41-03 recheck: logical record 1, order 51DB11EC11B1D, original price
  183,20 and date 01.06.2026; all raw fields available.

Desktop and 390px mobile screenshots were visually inspected. Zoomed images and
regions scale together; no page-level horizontal overflow. Final frontend rebuild
was replayed again successfully. Raw responses, original page images, screenshots,
GET-only browser script/results and final source hashes are in local tmp/m43.

Running Docker backend has all 24 workspace Python source files with matching SHA256;
three documents remain ready. No generation or embedding events since this deployment.
Ports remain frontend 18095 / backend 18094, existing runtime unchanged. No live model
calls, new uploads, key changes, paid-tier changes or benchmark runs occurred.

## Limits and next step

Highlighting identifies source regions, not proof of answer correctness. It can cover
more than a single fact. Raster zoom has finite detail; text remains the fallback.
Unsupported/unreliable coordinates are explicitly downgraded, not counted as successful
highlighting. An already open preview is a snapshot until reopened; there is no polling.
CSV citations remain whole-record references. This local demo adds no authentication,
public file service, original-file download or arbitrary page/path access.

M4.3 acceptance is complete. Next: M4.4 evidence-based reranking decision. Formal
benchmark, provider configuration and feature freeze remain later work. Full backend
and M5 clean-build acceptance were not run at this checkpoint.
