# M1 question set

Source of truth: m1_questions.json and ../material_manifest.json. There are 16 cases: 13 development and 3 holdout. Questions are in German or English; reference answers may be paraphrased provided all required facts and qualifications survive. This is a manual acceptance set, not an implemented automated test interface.

## Execution

Upload the original files through the application, select only allowed_documents, ask the question, and record retrieved evidence, answer, citation and result separately. Never ingest this JSON, reference answers, logs or development documents as user source material. The original data stays ignored by Git; acquire it from the SITECO download directory linked in ../materials.md and compare SHA256 against the manifest.

For answer cases, require all stated facts, correct model/record assignment, units/conditions and a citation to each supporting document and page/record. Equivalent number formatting is acceptable. A real citation alone does not prove support. For absence cases, distinguish no exact record from insufficient evidence. For unsupported content, explain the extraction limitation rather than assert the original contains no answer. Classify failures as parsing, retrieval/scope, calculation, generation or citation. Application results are all not_run; M1 preparation is not an accuracy score.

PDF page_number is the physical 1-based page, not an inferred printed label. CSV record_number is 1-based after the header, counted by a CSV parser, not physical line number; future quoted multiline cells must not break it. Header is not a data record. Evidence columns and order numbers disambiguate each record.

## Holdout protocol

Lunis R (lunis_holdout) is reserved as a whole document. H01/H02 were annotated from cached extraction and visual page 4 review only; no parser tuning or model-answer testing on it. H03 reserves the last two price records, 11385/11386, within the same CSV: this is a weak same-file holdout, not unseen-schema validation. Full CSV must still be uploaded and available to exact lookup; the holdout questions/answers must not guide development.

Apollon 21 and General Terms of Sale are additional whole-document reserves without scored questions yet. Their text has been machine-extracted; Apollon text was briefly read during selection. None is described as blind/unseen. Do not use reserve documents to tune prompts, parsing rules, chunking or thresholds. Run H01–H03 after a fixed implementation checkpoint in M4/M5; if subsequently used to fix failures, label them regression material and reserve fresh questions before another final check. A genuinely different-domain validation document remains future work, not a M1 claim.

Reference annotations were prepared by the assistant against source evidence; user review of the answer key remains welcome and must not be claimed as already performed.
