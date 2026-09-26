# M2.6 PDF hybrid retrieval: implementation proposal

2026-09-26. Stage baseline: 7a542df896d124470744c9924c8042b4aaeefdc0
(M2.5 committed and pushed). User subsequently approved the proposed tradeoffs
and authorized steps 1–3, then steps 4–6. All six retrieval steps are accepted;
see eval/results/m26_first_three.md and eval/results/m26_hybrid.md. The original
proposal below is retained for provenance; docs/m26-retrieval-contract.md is the
current implementation contract. M2.7 answering remains pending.

## Confirmed direction

The user explicitly selected two retrieval routes and RRF: SQLite FTS5 with
BM25 for lexical candidates, and Voyage embeddings with the already selected
per-document FAISS IndexFlatIP for semantic candidates. No database service,
Redis, extra worker container, OCR, visual reasoning or reranker is added.
CSV exact lookup stays independent; fuzzy PDF retrieval must not replace a CSV
exact miss. Existing evidence locators, ready gate, model/1024-dimension policy,
shared 3 RPM/10K TPM budget and held-out restrictions remain in force.

Current code has an unused in-memory BM25L adapter and a reusable RRF function.
BM25L is not SQLite FTS5 BM25; the production lexical route should use FTS5's
built-in ranking rather than creating a third redundant route. Existing RRF
ties follow first-seen order; source IDs and deterministic tie rules need tests.

## Evidence gathered without provider calls

Windows Python SQLite 3.49.1 and Linux test-image SQLite 3.40.1 both created an
FTS5 table successfully in memory. No live database was inspected. With the
default tokenizer, synthetic texts containing AB-123 / AB 123 and 12,5 / 12.5
were both matched by either corresponding quoted phrase. This exposes punctuation
loss, not a defect discovered in real development questions.

Official references checked:
- [FTS5 tokenizers, query syntax and BM25](https://www.sqlite.org/fts5.html):
  BM25 sorts lower scores first; corpus statistics use the whole FTS table.
- [Voyage embeddings](https://docs.voyageai.com/docs/embeddings): explicit
  input_type, output_dimension/output_dtype and truncation=False are available.
- [FAISS metrics](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances):
  normalized inner products implement cosine ranking.

## Proposed implementation slices and acceptance

1. Define the retrieval contract and source identity. Proposed T-007:
   retrieve(question, document_ids, top_k=8), returning actual scope, source
   records, route ranks/scores, fused rank and explicit route status/warnings.
   Validate all selected IDs before work; retrieval itself accepts ready PDFs,
   while mixed CSV/PDF routing belongs to M2.7. Identity is document_id plus
   evidence_id, not bare content-derived IDs. Confirm this new test boundary
   before implementing it. Acceptance: unknown/not-ready/wrong-type scope,
   independent duplicate uploads, deterministic order and no scope leakage.
2. Implement lexical storage/query generation. Preserve original evidence text
   and locator, index the existing retrieval_text separately. Start with ordinary
   persisted FTS content for simpler consistency, plus complete identifier/numeric
   search keys; avoid introducing a native custom tokenizer prematurely.
   Compile quoted literal terms safely; SQL parameters alone do not neutralize
   the MATCH expression language. Propose OR term recall initially, with exact
   phrase/literal evidence retained as diagnostics; no default stemming, fuzzy
   expansion, unit conversion or LLM query rewriting. Acceptance: German/English,
   hyphens, punctuation, leading zeros, decimal forms, umlauts, empty/no-hit
   queries, MATCH metacharacters, scoped top-N and restart/retry consistency.
3. Implement T-004 EmbeddingGateway and lock tested Voyage/tokenizer/FAISS wheels
   on Windows/Linux. Explicit document/query input_type, voyage-4, 1024 float32,
   truncation disabled. Count actual tokens including task overhead, batch within
   budget, cache by effective input/configuration and validate every returned
   vector/count/dimension/finiteness/norm. One shared bounded scheduler, query
   priority at the next available slot, finite timeout and bounded retries;
   retries also consume budget. No lock or database write transaction is held
   during provider waits. Acceptance uses fake clock/provider first, including
   quota sharing, cancellation, retry accounting, cache isolation and malformed
   vectors. Then one small document batch and one query, serially, using no
   held-out questions. Tokenizer resource cache stays on D:, no model weights.
4. Persist vectors as SQLite BLOBs and build per-document FAISS indexes with
   stable source mappings. Stage evidence/vectors; publish only when vectors,
   FTS and mappings are complete. Keep unpublished rows out of the live FTS
   corpus so their statistics cannot change ready retrieval. Restart rebuilds
   indexes from stored vectors without embedding. Acceptance: old ready sources
   readable, incomplete/failed/interrupted data unavailable, retry/corruption
   behavior, ties at the candidate boundary, preserved CSV functionality.
5. Produce one global scoped lexical list and one global scoped semantic list,
   then RRF their union. Proposed starting settings: 20 candidates per route,
   equal route weights, RRF k=60, final 8 records. These are baseline candidates,
   not tuned/approved thresholds. Do not fuse per document and truncate early:
   vector top-k merging properties do not prove RRF top-k equivalence. Preserve
   source attribution, route rank and original evidence. Acceptance: overlapping
   routes, no double vote within one route, stable ties, empty lexical route,
   candidate truncation and duplicated content in different uploads. RRF scores
   are ranking signals, never probabilities or sufficient-evidence certificates.
6. Docker/browser acceptance with a short development PDF first. Compute input
   budget before the complete file run; do not automatically launch a full model
   evaluation suite. Upload -> quota/processing -> ready -> evidence; invoke
   retrieval inside the backend through an acceptance-only harness, then recreate
   the container and check restoration. Compare lexical/semantic/fused evidence
   on a few development questions and log parse/lexical/vector/fusion failures
   separately. Full question answering remains M2.7, not accepted by retrieved
   evidence alone. No holdout tuning or automatic paid-plan changes.

## Choices still proposed, with alternatives and risks

- FTS corpus scope: recommend one persistent table containing only published
  PDF evidence, filtering requested IDs before LIMIT. Simple and maintainable,
  but BM25 IDF/length statistics still include unselected ready PDFs. Thus source
  isolation does not promise ranking invariance when unrelated ready files are
  added. Alternative: build a temporary FTS corpus for the selected scope (or
  compute scoped BM25 statistics), at extra rebuild/cache/implementation cost.
  Do not compare independent per-document raw BM25 scores as if calibrated.
- Exact identifiers/numbers: retain complete literal search keys in addition
  to ordinary tokens; validate raw evidence for explicit constraints. Do not
  automatically treat punctuation variants or units as equivalent. FTS alone
  does not implement numeric inequalities or guarantee parameter ownership.
  Specific tokenizer/key extraction rules require synthetic/development checks.
- Route errors: recommend explicit retrieval failure when semantic retrieval
  fails; quota wait is not a failure. Zero lexical matches is a normal empty
  route. Alternative is visibly labelled lexical-only degraded results, which
  needs a deliberate response/UI contract; no silent downgrade pretending RRF.
- Ranking: equal RRF initially; weighted RRF, reranking and LLM expansion stay
  deferred unless development evidence justifies them. Exact-looking matches
  can still concern the wrong product/parameter, while semantic neighbors can
  always exist for irrelevant questions. No arbitrary RRF score cutoff proves
  the document answers a question; answer constraints remain a later concern.
- Resource/latency: quota is the main likely latency constraint, not FAISS
  compute. Continuous query priority can delay ingestion. Token estimates differ
  from character chunk limits; an indivisible over-budget chunk must fail
  explicitly or be split under an approved evidence-preserving rule, never
  silently truncated. Cross-client quota consumption still permits 429s.
- Dependencies/recovery: native FAISS/NumPy wheels, tokenizer downloads, SQLite
  FTS synchronization, vector configuration drift and restart memory copies need
  actual checks. Existing unavailable-build PDF failures are nonretryable;
  recommend reuploading the short development PDF rather than silently
  reprocessing old failed records during startup.

The initial proposal above is retained for provenance. The user subsequently
confirmed T-007, the shared published-corpus policy, explicit failure rather than
silent degradation, and the baseline candidate sizes. Those choices are now
approved and implemented in steps4–6. See docs/m26-retrieval-contract.md for the
current implementation boundary and P-027 for later deterministic tool execution.
