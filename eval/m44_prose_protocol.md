# M4.4 prose development comparison protocol

Prepared 2026-09-27 before any live comparison. User requested this bounded
experiment; the user explicitly approved the outbound scope and US$0.10 cap
in the current conversation. No production
reranking adoption is implied. Previous mixed-sample decision remains historical.

Use eval/cases/m44_prose_development.json: 8 fixed German prose questions and 12
necessary page/text anchors over procurement terms, privacy statement and partner
code. All 10 relevant original pages were rendered and visually checked before the
first request. General Terms of Sale and all other reserves are excluded. Privacy
7.3 and 11.2 retention statements are distinct evidence, not reconciled legal advice.
These are document-content questions, not current-law verification.

Run in a new isolated runtime, using production DocumentService/DocumentProcessor,
PdfRetriever and evidence_context. No live SQLite access, no production uploads or
changes, no new public routes or model selection code. Corpus-wide BM25 statistics
will reflect these three legal documents; both arms use this identical corpus.

For each question, retrieve global lexical20 and semantic20 and retain their union
in RRF k60 order (top_k=40 at the existing retrieval seam). Baseline takes first8.
Voyage rerank-2.5-lite ranks exactly this same candidate union using retrieval_text
(body plus source context), truncation disabled. Reordered first8 retain the same
source records, IDs and coordinates. Reuse unchanged evidence_context with its
28,000 serialized-character budget for both arms. Rerank scores are logged separately,
not injected into source serialization, to avoid changing context size unfairly.

Before running: freeze question/material/parser hashes, configuration and this
protocol; verify every anchor maps uniquely. Save the full candidate set, route ranks,
RRF/rerank order, final8, actual context IDs, omissions and required-anchor coverage.
Report per-question required units in candidates/final8/context and complete-context
cases, plus first required evidence rank. Non-required fragments are not automatically
irrelevant, so do not claim a precision score from incomplete relevance labels.

Record ingestion separately from query retrieval and reranking. Include provider
service duration separately from deliberate quota pacing; report individual values,
not stable P95 or an end-to-end answer speedup. No answers are generated in this step.
A retrieval gain is not an answer-quality gain.

Approved live ceiling: at most 8 document embedding calls, 8 query embedding calls,
8 rerank calls, serial, first provider failure stops with saved evidence, no automatic
retry or model switching. Existing key only; no billing-plan modification. Apply
pre-call conservative input-byte cost estimates against the separately approved
US$0.10 cap, and log actual server token usage when available. Account quota remains
unknown until checked; no free-credit availability is assumed.

Decision rule fixed before outcomes: retain RRF if there is no improvement in required
evidence entering actual context, or a loss of a necessary condition/exception. Rank
movement alone is not enough. If context coverage improves without regression, identify
the exact improved cases and measured latency; propose bounded paired answer checks
before production adoption. Such calls need separate Gemini authorization. If only
one case improves, describe it as narrow evidence, not a generally established gain.
Do not tune candidate size, weights, parser, questions or expected anchors after the
run. Preserve failures; additional trials require a stated reason and authorization.

Production integration, if later justified, still requires a reviewed error/fallback,
quota/deadline and test-interface contract. This is development, not M5.0 evaluation.
