# M5.0 Evaluation Protocol v0.1

2026-09-27. **A+B and their outbound budget were approved (decision P-040); C was not approved. The formal run had not started when approval was recorded.**

Delivery edition: English translation of the approved protocol, with local process-document links replaced by the retained [case set](cases.json). Scoring rules, questions, configurations and budgets are unchanged. The `protocol_sha256` in `manifest.json` identifies the original Chinese bytes, not this translation. The original is available in Git history at `c5421f2:eval/results/m50/run-20260927-ab-01/protocol.md`; the source protocol used by the live runner is at `859447f:docs/m50-evaluation-protocol.md`. The original runtime file used LF except for its final two line endings, which were CRLF; Git normalizes them to LF. Reconstruct those two endings when checking the historical byte hash. All preparation-time statements below describe the original protocol, not the current delivery status.

## 1. Decision summary

The proposal was to approve A (12 baseline turns and three retrieval routes) and B (reranking the same candidates for seven queries), with C (four paired fixed-evidence generation cases across two models) decided separately. A is the main evaluation. B measures retrieval gains. C compares generation only, not a second model's entire planning pipeline.

The approval covered:

1. The case set, manually checked evidence standards, denominators and failure scoring below, and descriptive reporting rather than an improvised overall accuracy threshold.
2. Execution of A and the choice of B/C.
3. Disclosure of the specified materials to the named providers, request limits and a combined USD2 estimated-cost control. No account upgrades, automatic top-ups or paid-tier changes. If an account requires separate payment activation, pause for approval.

This authorization excludes later clean-runtime M5 delivery acceptance, post-fix reevaluation and manual retries.

## 2. Frozen baseline and local checks

Product commit: `7811243937e67e4e4d02854ffc616ad69736204d`. Handoff commit: `6c6d9222b414ac1747c094536fa784b0aa19a3a5`. On 2026-09-27, local main matched the remote and the working tree was clean before preparation; the handoff changed only three documents.

The existing demo was healthy with four ready documents, Gemini, Top K 8, reranking off and voyage-4. Its settings and database must remain untouched. A uses an independent evaluation runtime and frozen code, with all five materials ready before scoring. Existing indexes/caches must not be copied. Later delivery acceptance requires another empty runtime. Fix the complete corpus because FTS5/BM25 statistics cover the index table even when an individual query selects a smaller scope.

Use five complete originals, with paths and SHA256 values in the case JSON: procurement terms (4 pages), Rondel (2 pages), privacy statement (12 pages), Lunis R (4 pages), and the full 11,386-row price CSV. Do not trim the CSV to target rows. Highbay, scanned declarations, the partner code, Apollon and General Terms of Sale are excluded; the last two remain reserved.

All five hashes were checked locally. Text and rendered pages were inspected for terms pages 1/2, privacy pages 5/6/10/11, Rondel page 2 and Lunis page 4. CSV records 1/2/11385/11386 and the three absent orders were checked exactly. Preparation artifacts were local-only. No provider calls or application holdout questions had run during preparation.

A contamination audit found no prior application results for H01/H02/H03 or Lunis in evaluation results, logs or scripts. Earlier annotation/source reading is not blind testing. E10/E11 are two correlated questions from one held-out PDF; E12 is a weak holdout using the last two rows of a previously used CSV. All originals had been machine-scanned. If further prior use is discovered before execution, revise and refreeze the split rather than silently replace questions.

## 3. Questions and execution order

There are 12 scored turns in 10 conversations. E03 -> E04 -> E05 form one three-turn conversation; all others start a new conversation. Run development E01-E09, then holdout E10-E12, without tuning between groups. Ingest all materials before the first question.

- E01: payment-clock prerequisites, payment options and defect qualifications; terms page 2.
- E02: different retention periods and qualifications for general applications and onlyfy; privacy pages 5/6/10/11.
- E03: colour temperature, luminous flux, power, control and weight for two Rondel orders; page 2.
- E04: follow up on the second luminaire's colour temperature and power, retaining the E03 conversation and PDF scope.
- E05: continue asking its power, but select only the price CSV. The order is absent in that file; do not copy 9 W from history.
- E06: one CSV order's price and validity date; record 1.
- E07: two CSV orders' prices and EANs; records 1/2.
- E08: exact miss for a synthetic order; no substitution with a similar order.
- E09: partial answer across terms and CSV: Incoterms 2020 plus an exact miss for another order.
- E10: held-out Lunis diameter, weight and luminous-flux range; page 4.
- E11: held-out Lunis recessed-version colour restriction; page 4.
- E12: weak-holdout CSV prices and dates for two orders; records 11385/11386.

The case JSON preserves the exact German/English questions. E12 explicitly asks for dates to align the question with its existing reference standard. Do not translate questions before sending them to the model.

If E03/E04 fails, retain the first result and continue only if the application permits it. Otherwise mark subsequent turns `dependent_blocked`, keep them in the 12-turn denominator and score them zero. Never inject reference answers to repair history. The isolated E04 retrieval control appends a newline and `Resolved conversational subjects (not evidence): 0MD5307L0940` to its original question. This fixed control is not evidence of successful live reference resolution.

These turns do not cover all acceptance requirements: no additional OCR/scanned upload, cross-file duplicate orders, missing prices, refresh/highlighting or service-failure tests. Historical controlled checks may be cited as such, not as tests performed in this run. Cross-PDF comparison and a standalone pure-PDF no-answer case are also absent. E05 covers insufficient evidence after a scope change; E09 covers a mixed-scope partial answer. Do not claim full feature coverage.

## 4. Evidence and scoring

Evidence units are anchored to document hash, physical page, content/table row and header, not chunk IDs. Multiple top-eight passages may jointly satisfy a unit; duplicate passages do not earn extra credit. Semantically equivalent evidence in body text, retrieval_text or actually supplied source context is acceptable when ownership is explicit. A matching page, keyword or number without the necessary ownership/qualification is insufficient. Record reasons for equivalent locations; do not relax standards after seeing results.

For E02, pages 5/10 establish section ownership and pages 6/11 contain periods. A passage carrying accurate section context may satisfy the ownership unit without requiring a separate chunk. For E03, use the order-specific rows: an overview weight of 1.7 kg cannot replace the two rows' 1.6 kg.

The 40 required facts are binary: complete semantic compliance earns one; otherwise zero, with no partial credit. Equivalent decimals, unit conversions and paraphrases are allowed; EANs/order IDs must match complete strings. A fact may contain an indivisible conditional relationship. Do not weight by sentence length. Record additional unsupported claims/contradictions separately; extra correct facts cannot offset them.

The evaluator checks each item against original pages/records and records score_reason and evidence locations for review. This is not independent double-blind human annotation, and an LLM judge is not the sole ground truth. Record disputed annotations separately without changing denominators after seeing scores. If a standard is genuinely incorrect, retain v0.1 and its scores and publish the revision and affected scope.

### 4.1 PDF retrieval

Seven fixed positive rounds: E01/E02/E03/E04/E09/E10/E11; five development and two holdout. Their required-unit counts are 2/4/2/1/1/1/1: 12 total, 10 development and 2 holdout.

- Per-query Evidence Recall@8: satisfied units / required units. Primary aggregation is query-level macro average, reporting development (5) and holdout (2) separately; also report micro hits/12 and group hits/10 and /2.
- Complete-evidence hit rate@8: questions satisfying every unit /7, with groups /5 and /2.
- MRR@8: reciprocal rank of the first single result satisfying at least one entire evidence unit; zero if none of the first eight does so. Macro denominator is 7. If multiple passages jointly satisfy a unit but none does alone, Recall may be positive while MRR is zero.
- Also score coverage after the 28,000-character context budget, distinguishing candidate absence, ranking loss and context omission.
- CSV-only questions are excluded from PDF recall. Retrieval failures score zero in the fixed denominator and are counted separately; do not fabricate an empty retrieval response for an unexecuted query.

Precision@8 is not required because all candidate relevance has not been exhaustively annotated.

### 4.2 CSV

A returned record is identified by (document hash, logical record number). Deduplicate repeated citations for set scoring and report duplicates separately.

- Positive cases E06/E07/E12 contain five expected record occurrences across three questions (1/2/2). A record repeated across different questions counts once in each question. Per-query Precision = correct intersection / actual returned count; Recall = correct intersection / expected count. Empty positive returns score zero for both per-query metrics.
- Report three-query macro averages, micro precision = total intersection / total returned, and micro recall = total intersection /5. Separate two development questions (3 occurrences) from one weak holdout (2 occurrences).
- Exact-miss cases E05/E08/E09 pass only if the correct literal order was queried, returned no records and was explicitly reported absent in the current file. Denominator is 3. Timeout or an unexecuted lookup is not a correct empty set. E09 must also answer the supported PDF part.
- This material set has no positive duplicate-source case. Report duplicate preservation as N/A, not 100% based on old tests.

### 4.3 Answers, citations and behavior

- Required-fact coverage: correct facts /40; development /31, holdout /9 (document holdout 5, same-file holdout 4). E05/E08 contain zero required facts: fact coverage is N/A, but behavior is still scored.
- Citation coverage: correct required facts with accurate, locatable and semantically supporting citations /40, with the same splits. Valid citation IDs alone are insufficient.
- Citation support: supported factual-claim/citation pairs / all output pairs of that kind. Publish the observed denominator. With no citations, support is N/A and required-fact citation coverage remains zero where applicable; silence cannot earn full marks.
- Strict turn pass /12: correct expected behavior, all required facts correct, complete required citations, no additional false facts or out-of-scope evidence. Unsupported currency/tax/discount additions fail CSV cases. An exact-miss status and lookup receipt can establish absence; do not invent a source citation.
- Reference resolution /2: E04/E05 must identify 0MD5307L0940. Current-scope compliance /2 is separate. Answering historical 9 W in E05 fails; reporting the order absent from the selected CSV can pass.
- Negative/partial-answer behavior /3: E05/E08/E09. Entirely refusing E09 or substituting a similar order fails.
- Record unsupported_claims, wrong_attribution, missing_qualification, out_of_scope and per-turn reasons separately; do not hide them in a weighted composite.

No unsupported threshold such as 80% overall accuracy is introduced. Evaluation completion means an auditable result or nonexecution reason for every planned item, complete metrics and failure analysis, not universal success. Violations of required behavior must be assessed for minimal blocker fixes under the freeze rules, while preserving original scores.

## 5. Comparison configurations

**A: twelve-turn Gemini end-to-end baseline.** gemini-3.5-flash-lite; PDF RRF Top K 8; reranking off; 20 lexical and 20 vector candidates; equal-weight RRF k=60; voyage-4/1024/float, L2 normalization and FAISS IndexFlatIP; 28,000-character evidence budget. Prompts, schemas and parsing parameters come from frozen source and are hashed. Temperature, seed and thinking are not explicitly set by the adapter: record provider defaults, not determinism. Output limit 6,000; generation-call timeout 60 seconds; total question budget 240 seconds including waiting.

The isolated retrieval comparison uses the same seven fixed queries, complete corpus, vectors and indexes for lexical top8, vector top8 and RRF top8 (21 local scored results). Observability belongs in the harness, not new product HTTP interfaces or altered retrieval algorithms. Fixed queries are embedded first and cached; later cache hits are explicitly warm, not cold-start timing. Live E04 resolution may produce another query embedding, recorded separately without replacing the fixed-query comparison.

**B:** rerank the same deduplicated 20+20 candidate union for each of the seven queries using rerank-2.5-lite, returning eight. Record candidate hashes, input order, ranks, five-second budget and actual rerank/fallback status. Report actual strategy results including fallback and successful-rerank subsets separately. B does not rerun twelve-turn generation, so it supports retrieval-coverage conclusions only, not claims of improved answers.

**C (not approved):** use development E01/E03/E06/E07 with the exact RRF/CSV evidence bundle actually supplied to A's answer stage. Copy identical bytes to Gemini and Groq openai/gpt-oss-120b. Each generates once; a calculation request may use the existing tool followed by one final answer, at most eight calls per model. Do not include reference answers, select passages based on answers, trim long inputs or change Top K. Cases without a valid A bundle are unpairable, with no replacements. Fix ANSWER/schema, alternate provider order and preserve request hashes. No new retrieval, resolution or planning calls; C results are excluded from A's main score.

Groq feasibility uses the observed 8,000 TPM account limit, not local throttling as evidence of quota. Conservative preflight includes input estimates and 6,000 reserved output tokens. If clearly oversized, send neither side and record noncomparability. On 413/429, retain the first failure and stop C for a decision; do not shrink inputs or change paid tiers. Report successful pairs /4; zero valid pairs is possible.

Caching refers to application query embeddings. No explicit provider context cache or answer cache is enabled, and reference answers are never injected. Record observable automatic provider caching, otherwise unknown. Each turn runs once; make no stability/significance claims. Run the twelve end-to-end turns serially in their original order, and do not compare latency across cold/warm cache conditions.

## 6. Disclosure, request limits and cost

Disclosed content:

- Voyage embedding: parsed text from four complete PDFs (22 pages), titles/context and fixed/actual PDF queries. No CSV embedding or original PDF binaries.
- Voyage rerank (B only): seven queries with up to 40 candidate texts each, including candidates beyond reference-answer evidence within scope.
- Gemini (A/C): questions, filenames/metadata, bounded history, retrieved evidence, selected CSV records, tool results and structured prompts. No complete CSV or reference-answer file.
- Groq (C only): corresponding terms/Rondel evidence and CSV records 1/2 with the four questions/prompts. No Lunis holdout or privacy statement.

Count actual outbound attempts, including failures. Category budgets cannot be moved to add questions or retries.

A generation: about 18 calls on an ordinary successful path, cap 32. Per-case caps: E01/E02/E03/E10/E11 each 2; E04 3; E05 4; E06/E07/E08/E09/E12 each 3. PDF-only questions need no planning call; E04/E05 include resolution. Early returns do not authorize extra reruns.

A embedding: at most 24 logical document batches of at most 4,000 counted tokens each, with up to three existing gateway attempts per batch: 72 outbound attempts. Query cap: 14 logical requests (7 controls plus up to 7 distinct end-to-end queries), up to three attempts each: 42 attempts. Combined embedding cap: 114. Stop even if ingestion is incomplete. Count at the provider boundary, retain failures and actual batch counts; do not execute if reliable counting is unavailable.

B cap: 7 rerank attempts, no retries. C cap: 8 Gemini and 8 Groq calls, no adapter retries. Total caps: A=146, A+B=153, A+B+C=169. These conservative ceilings include embedding retry allowances, not expected usage. No additional Settings probes, debugging or warm-up calls. Authentication failure stops the affected provider block. Retryable embedding errors/429s use only the frozen gateway policy within the run cap; preserve first failures and all subsequent attempts.

Public synchronous-text list prices checked on 2026-09-27, before free credits:

- Gemini: USD0.30/million input tokens; USD2.50/million output tokens including thinking. [Pricing](https://ai.google.dev/gemini-api/docs/pricing).
- Groq: USD0.15/million input; USD0.60/million output. [Model page](https://console.groq.com/docs/model/openai/gpt-oss-120b).
- voyage-4: USD0.06/million; rerank-2.5-lite: USD0.02/million. [Pricing](https://docs.voyageai.com/docs/pricing). Conflicting free-allowance wording was not relied on; assume no free allowance.

Estimated-cost controls: generation input, including system/payload/schema and conservative envelope allowance, must be at most 50,000 tokens; output cap is 6,000. Prefer the relevant local tokenizer. Without one, use UTF-8 byte count plus envelope allowance conservatively; pause if the bound cannot be established rather than trim input. Embedding upper bound: 114 x 4,000 = 456,000 tokens. Rerank counts query_tokens x candidate_count plus total candidate tokens, at most 160,000 per attempt, checked before sending.

Estimated upper bounds without free credits: about USD0.99 for A, USD1.01 for A+B and USD1.34 for A+B+C. The approved USD2 control leaves accounting/envelope headroom. These are price-based estimates, not invoices or promises of actual spend. Record available usage; missing usage is estimated/unknown, not actual billed cost. Pause if preflight exceeds budget, prices change or request/input bounds cannot be enforced. Free accounts still obey attempt caps; do not activate payment automatically.

## 7. Results and presentation

Planned outputs:

- manifest.json: versions; protocol, cases, materials and prompt hashes; environment/configuration, cache policy, budget and usage.
- attempts.jsonl, retrieval.jsonl, answers.jsonl, scores.jsonl: safe per-attempt metadata, candidates/ranks/actual context, original answers/citations and per-fact/evidence judgments with reasons. No keys or authorization headers.
- summary.json, summary.csv and report.md: grouped denominators, actual paired-model counts, failure attribution and conclusions. Retain safe provider response fields with real usage when available.
- A local interactive report derived from summaries and per-case files: retrieval comparison, case matrix, model-pair differences, timing/waiting and source locations. No new product page or public hosting.

Report actual per-turn timings and medians with success/failure sample counts. Do not silently exclude failure durations. Unobserved stages are unknown, not inferred from total duration. Freeze first-attempt scores; retries or post-fix runs use a new run ID and never overwrite old results.

Conclusions apply only to these five materials, twelve turns and frozen configuration. Separate development, document holdout and weak same-file holdout. Correlated E03-E05 turns are not twelve independent statistical samples. No confidence intervals, significance, P95 or universal model leaderboard. Classify retrieval failures as parsing absence, candidate absence, ranking loss or context omission; distinguish end-to-end planning/resolution, generation ownership/qualifications, citation display and provider failures.

## 8. Execution after approval

Record approved scope and protocol hash, establish a specific post-approval evaluation commit while retaining product baseline 7811243, and implement the minimal local logging/budget harness. First verify counting, stop conditions and no unintended outbound calls using controlled providers at existing test seams. Any necessary new interface boundary must be reviewed before implementation.

Prepare all five originals in an independent runtime using frozen code; execute A, then approved B/C. Do not tune after holdout results. Preserve blocker results, propose minimal fixes and refreeze before a later run. Clean-runtime delivery acceptance needs its own plan and outbound budget, not unused allowance from this protocol.
