# M2.6 retrieval and embedding contracts

Approved by the user's authorization of the first three steps and acceptance of
the preceding recommendations (P-026). Stage baseline: 7a542df.

## T-007: PDF retrieval

`PdfRetriever.retrieve(question, document_ids, top_k=8)` validates a nonblank
question (at most 8,000 characters), explicit nonempty string document IDs and
integer top_k 1–100 (not bool). Scope deduplicates IDs in first-request order.
Every selected document must exist, be ready and be a PDF. Errors are invalid_query
(422), document_not_found (404), document_not_ready (409), document_not_pdf (422).
The whole scope is validated before retrieval; no silently dropped documents.

The hybrid result contract contains document_ids, route status/warnings,
and ranked evidence records with document_id, evidence_id, original source text,
locator, lexical_rank/score, semantic_rank/score and fused_rank/score. Absent route
membership is null, not a fabricated zero score. Scores are ranking signals, not
answer confidence. Source identity is the pair (document_id, evidence_id).

Steps 4–6 connect production publication and hybrid execution. Missing gateway
configuration raises retrieval_not_configured (503); semantic provider failures
are explicit errors, never lexical-only success. There is still no production
query HTTP endpoint; M2.7 will call this backend method.

The approved lexical acceptance entry is
`PdfRetriever.lexical_candidates(question, document_ids, top_k=20)`, using the
same scope gate, returning document_ids, route='lexical', records. It is a
diagnostic/internal route, not a fallback for retrieve and not a production HTTP
endpoint. Each row includes the original evidence and locator, lexical_rank
(1-based), lexical_score (lower is better), and matched_literals.

`FtsStore.replace_document(document_id, evidence)` transactionally replaces one
document's lexical snapshot, preserving others. Duplicate evidence IDs within
one document are rejected; identical IDs in different documents remain distinct.
The publication owner supplies its SQLite transaction through connection= so
FTS, PDF artifact and ready status commit together. Shared FTS
statistics include all indexed documents, while candidate filtering precedes
ORDER/LIMIT. Selected-source isolation does not imply BM25 ranking invariance.

Search text uses NFC/casefold consistently at index/query time (including ß→ss),
without rewriting returned source text. Unicode61 retains diacritics; no stemming,
accent stripping, synonyms or LLM expansion. Generated quoted OR terms are used,
not raw MATCH grammar. Complete alphanumeric terms containing digits, optionally
joined by hyphen/dot/comma/slash and signed numeric terms, receive reversible
hex-encoded literal keys; their punctuation/leading zeros stay significant.
Plain words use the text field. Pure literal queries therefore distinguish
AB-123 / AB 123, 12,5 / 12.5, 0012 / 12 and -5 / 5 in tests.

Ordinary words in a natural-language query may also retrieve candidates without
the specified literal; matched_literals exposes this. No candidate is asserted
to satisfy a numeric condition. Compact 20W and separated 20 W need not match
identically. Unicode dash variants, decimal/locale ambiguity, unit equivalence
and product/parameter ownership are not guessed. Future validated tool plans
may call deterministic Decimal/whitelisted-unit operations against grounded
fields; no arbitrary code execution or LLM arithmetic is added here.

## T-004: EmbeddingGateway

`embed(texts, input_type, *, stop=None, on_wait=None)` returns an N×1024 float32
array in original input order. input_type is document/query; texts are nonempty
strings in a nonempty list. Duplicate texts are embedded once per call. The hosted
adapter uses voyage-4, output_dimension=1024, output_dtype=float, truncation=False.
It does not normalize vectors; the publication owner normalizes once in float64,
converts to float32 and stores exactly the vectors added to FAISS.

Validate all returned vector counts, dimensions, numeric types, finite values
and nonzero norms before caching the batch. Partial valid earlier batches may
remain cached if a later batch fails; no partially completed document is published.
The SQLite cache stores little-endian float32 BLOBs, keyed by provider/model,
dimension/dtype, input_type, truncation, vector-format version and exact input
text. The effective input includes parser-provided context. Invalid cache entries
are misses. Model/config changes cannot reuse incompatible cache entries.

The backend owner must share **one BudgetScheduler instance** between ingestion
and queries. One active provider call, at most 32 pending tickets, FIFO within
priority, query priority at the next slot, no preemption of an active call.
Rolling 60-second limits: 3 requests and 10,000 reserved tokens; additionally
space request starts at least 20 seconds apart. Failed attempts are not refunded.
Admissions and server cooldowns persist in SQLite; restart cannot reset the
recent budget. Provider usage above the reservation increases the ledger charge.
This is a single-backend-process design, not cross-process/distributed scheduling.

Use pinned voyage-4 tokenizer JSON with checksum validation, no truncation/padding,
and count the complete task-prefix-plus-text. Reserve 16 extra tokens per text.
Batches are at most 4,000 reserved tokens. A single item exceeding that budget is
rejected as embedding_input_too_large before any request in that call; it is not
silently truncated or split away from its evidence. This conservative batch rule
may reject a source chunk even below the model's own context limit.

Use fake clocks/providers for rate tests. Each admission waits at most 180 seconds;
cancellation is checked during waits and after provider return. At most three
attempts per batch for transient failures, all through the same quota gate.
429 Retry-After is honored as a shared persistent cooldown; absent/malformed
values use 60 seconds. Very long server waits hit the admission deadline instead
of retrying earlier than requested. SDK and HTTP transport retries are both off.
Requests connect/read timeout is 30 seconds each; it is not a force-kill or strict
total socket lifetime. Error messages never include provider bodies or keys.

Fixed error codes include embedding_invalid_input, embedding_input_too_large,
embedding_invalid_vectors, embedding_invalid_usage, embedding_interrupted,
embedding_queue_full, embedding_wait_timeout, embedding_authentication_failed,
embedding_rate_limited, embedding_provider_unavailable and embedding_provider_error.
No silent lexical downgrade, automatic paid-plan switch, OCR or local model.

## Preparation and staged integration

Use scripts/prepare_voyage_tokenizer.py with an explicit D-drive runtime/tokenizers
directory. It downloads only the pinned ~7 MB tokenizer JSON and verifies SHA-256;
runtime loading makes no Hugging Face call. The file is not in Git/images.
Keys are supplied to the backend adapter only; the opt-in acceptance script reads
the explicitly named ignored key file without printing it. No normal test uses keys.

FAISS CPU 1.15.1, Voyage 0.5.0 and tokenizers 0.23.2 are locked and verified on
Windows/Linux. The SDK brings additional transitive LangChain/LangSmith packages;
the application does not use their splitters, orchestration or tracing. No local
model extras/weights are installed. The backend lifespan constructs one configured
gateway shared by DocumentProcessor and PdfRetriever. It requires voyage-4 and
DATA_DIR/tokenizers/voyage-4-tokenizer.json. Missing key preserves explicit
retrieval_not_configured; invalid tokenizer/model produces a sanitized
embedding_configuration_invalid error after the parsing checkpoint.

## Complete publication and fusion (steps 4–6)

pdf_artifacts stores JSON evidence/configuration, little-endian float32 vector
BLOB and a digest covering both. Configuration includes parser version, model,
dimensions, dtype, normalization and index type. The prepared evidence and
vectors are detached, validated and built as IndexFlatIP before a transaction
writes the artifact, replaces FTS and sets ready. The lifecycle lock covers only
publication, never remote calls or quota waits. Failed/unfinished artifacts cannot
enter the live FTS corpus. Retry clears the document artifacts and lexical rows;
the content/configuration embedding cache remains reusable.

Startup validates each ready artifact's digest/configuration/shape/source mapping
and unit norms, reconstructs FAISS from its vectors, and rebuilds FTS from those
same sources before serving. It neither parses nor embeds. A bad artifact becomes
index_restore_failed and is excluded; other ready documents remain available.

Retrieval snapshots only selected published indexes, releases the lifecycle lock
for query embedding, then validates that publication is unchanged before reading
lexical candidates. Each FAISS flat scan enumerates the selected document's rows
to preserve ties at the candidate boundary; a single global list sorts by score
descending then document_id/evidence_id and takes 20. FTS filters the entire
scope before its global BM25 top20. No per-document fusion or truncation occurs.
This exact, simple scan is bounded by the current document/page limits; larger
corpora would require performance evaluation rather than an untested scalability claim.

RRF uses the existing function, fixed lexical-then-semantic route order, equal
weights and k=60. Ties preserve first-seen order; both route lists already have
stable source tie breaks. Composite IDs prevent different uploads collapsing.
The union is cut to requested top_k (default8; at most40 distinct candidates).
Each output includes both route ranks/scores (null if absent), fused rank/score,
original text, retrieval_text, context/source_spans and locator. routes contains
status='ok' and candidate count for each route; warnings is currently empty.
Document extraction warnings remain in document status and must be considered
by M2.7; successful retrieval does not remove them or prove answer support.

P-027 records the confirmed M2.7 structured-conditions/deterministic-tools decision.
The initial ranking settings are not tuned parameters. Development-only Docker
results and observed candidate noise are in eval/results/m26_hybrid.md.
