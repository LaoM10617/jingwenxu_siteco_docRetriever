# Minimal evidence source structure

Confirmed for implementation planning by the user's M1 request to determine the necessary source structure. This describes required semantics, not a new HTTP endpoint or an implemented data model.

## Document identity

Store document_id (an opaque upload identity), original_filename (display only), content_sha256, and media_type. Same filenames are not identity; identical bytes need not imply the same selected upload. Keep the mapping to the actual stored upload. A download URL is optional provenance, not a substitute for the uploaded bytes. Local absolute paths are not exposed as citations.

## Evidence identity and location

Every indexed evidence unit has evidence_id (stable within that parsed document version), document_id, text (source-derived content), and locator. A citation resolves to stored evidence, never to model-invented filenames, pages or row numbers. Content changed or reprocessed with changed segmentation must not reuse stale evidence IDs.

PDF locator: kind=pdf and page_number (physical page, 1-based). Keep each baseline evidence unit on one page; a multi-page answer cites multiple units. A heading/section label is optional human context. Coordinates may be retained internally for layout grouping; bounding boxes and visual highlighting are not required for the first citation interface.

CSV locator: kind=csv and record_number (1-based data record excluding header). Preserve header names and the ordered raw row values; citation can identify columns used. For the price dataset, also preserve the Bestellnummer value as an exact-match key. Record number is not a physical line or a pandas index. A normalized Decimal price is derived data and must retain its raw value and explicit parsing rule. Do not invent currency from locale or filenames.

A parameter-table evidence text includes the model/group heading, headers/units, applicable rows and qualifications. If a unit cannot carry those relationships reliably, it cannot justify a precise parameter answer merely because its numbers were extracted.

## Selection and answer behavior

An explicit set of selected document_ids determines eligible evidence and exact CSV lookup scope before ranking/top_k. Multiple uploaded price files may contain the same order number: return source-specific records or seek clarification; never silently overwrite or assume the latest date wins. A missing exact order match is different from failed parsing or an unselected document.

Answers cite evidence_id references, resolved by the application to filename plus page or record/key. Validate that cited evidence exists and belongs to the selected set. That check does not prove factual support; acceptance questions also inspect whether the cited content supports the claim.

No usable text means unsupported/failed processing with an explanation, not an empty searchable document that proves absence. Partially readable files need an explicit limitation; the exact processing state machine and automatic detection mechanism are M2 implementation decisions.

## Deliberately deferred

Storage classes, HTTP schemas, parser adapter interface, complete processing states, upload size/page limits and model/tool contracts are not specified here. Confirm material interface and dependency choices before implementation as AGENTS requires. No additional class hierarchy, persistence service, OCR or visual highlighting is implied.
