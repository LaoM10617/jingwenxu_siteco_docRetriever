# M4.4 reranking decision

2026-09-27. Inspected main `2f3ad2de62d0be220d231cd7d800a02e4c1b0353`.
Decision: do not introduce a reranker in this iteration. M4.4 is complete as a
development decision, not a benchmark or proof that ranking cannot improve.

## Evidence and failure layer

- M41-06 resolved "the second luminaire" as an exact CSV key. The saved task has only
  lookup_orders, zero results, no PDF retrieval and no final answer-generation step.
  This is reference-resolution/planning failure. M4.2's bounded recheck queried the
  intended 0MD5307L0940 correctly, without changing PDF retrieval.
- The historical M3 ordinal failure had the intended product in the provided Rondel
  source, alongside the other model. Generation rebound "second" to a table row.
  Reordering whole passages cannot enforce ownership within that shared passage.
  Explicit subject binding addressed the observed case; semantic risk remains.
- M41-04/05 correctly associated the two products and follow-up parameters. M41-08
  preserved the written-agreement condition. These cases give no demonstrated
  ranking-induced omission of the requested facts.
- M41-01 and M41-07, plus the dependent cache observation M41-09, show 7 included /
  1 omitted passages. The required Incoterms 2020 source remains cited correctly.
  Omission is a context-capacity signal, not by itself a quality failure or proof
  that a reranker would help. The omitted passage and its relevance cannot be
  recovered from these public task results.
- Refresh selection and source readability failures belong to interaction and have
  separate M4.2/M4.3 evidence. Historical provider quota waiting is not evidence of
  ranker latency; no reranker speed/quality comparison was run.

Sources: [M4.1 original findings](m41_development.md), [M4.2 repair](m42_experience.md),
[M3 initial failure and recheck](m35_integration.md). This inspection also reread the
saved raw M41-01 through M41-09 tasks and the fixed M41-06 task; none were resubmitted.

## Code cross-check and retained baseline

PdfRetriever takes global lexical and semantic lists of at most 20 each, fuses their
union using equal-weight RRF k=60, and the question path uses the default final 8.
CSV exact lookup has no PDF reranking stage. evidence_context admits whole evidence
items under 28,000 serialized characters, skipping items that do not fit; it does
not truncate source qualifiers. No retrieval/answer-context code changed between
the M4.1 baseline de8487d and the inspected commit.

Keep this baseline and the existing models/index unchanged. Add no dependency,
provider, external request, evaluation framework, public tracing API or parameter
change. No new tests or model calls were needed for this read-only decision.

## Limits and reopening criteria

Public task records expose route counts, context counts and selected citations, but
not the full candidate lists, fused ranks or omitted source identities. Even cited
sources do not retain ranking fields in these saved results. This evidence cannot
establish Recall@8, optimal ordering, absence of retrieval misses, or universal lack
of reranker benefit. Do not replace the missing traces with assumptions.

Reopen only after a concrete development case shows relevant evidence in the
candidate union but lost below final selection, excluded from the context budget,
or demonstrably displaced by distracting passages. First record candidate identities,
ranks, final context and original-page relevance through the existing retrieval/test
interfaces; agree any additional test seam before implementing it. Evidence absent
from the candidate union instead calls for parsing/query/recall investigation.
Evidence already correctly present calls for attribution/generation diagnosis.

If a reranker becomes justified, separately confirm its dependency/provider and
outbound authorization, then compare the same cases, scope and other settings for
evidence coverage, answer improvement and added latency. Preserve failed results
and explicitly budget the experiment; protect M5.0 and M5 time. Do not use held-out
questions for tuning. If a frozen evaluation reveals a defect, follow P-032's explicit
unfreeze/refreeze and contamination disclosure rules.

Next: M4.5 provider configuration; confirm its configuration/key lifecycle and task
snapshot interface before implementation. Feature freeze and formal evaluation remain
pending. M4.4 changes only decision/README/plan/handoff records; no commit or push.


## Follow-up: prose-document scope clarification (not adoption approval)

The user questioned whether the mixed development sample represented the likely
prose-PDF workload. It does not: M4.1 used procurement terms (4 pages), Rondel
(2 pages) and the price CSV. Its legal facts were concentrated on procurement page 1.
The case does not prescribe Legal Documents as the official corpus; treating prose
PDFs as a main demonstration baseline is a reasonable project choice, not an inferred
employer requirement. P-034 remains limited to the observed sample.

Additional existing evidence: M2.6 reported generic/title-only passages at fused
positions 3/4 in a Rondel query, while the required evidence was first. Thus candidate
noise has been observed; an answer-quality benefit from removing it has not been
measured. See m26_hybrid.md. This makes a bounded prose development comparison
reasonable, without asserting beforehand that a reranker will help.

Local parsing only, no embedding or generation: procurement terms 4 pages/29 chunks,
no warnings; privacy statement 12 pages/29 chunks, one degraded page; business-partner
code 6 pages/8 chunks, two degraded pages. Degradation is layout_uncertain, not a
measured retrieval failure. General Terms of Sale (10 pages) remains a whole-document
reserve under the existing manifest; its content was not used for this investigation.
The first metadata-print attempt hit Windows console encoding for the German filename;
ASCII-escaped output succeeded, with no parser change.

Proposed, not executed: 6–8 fixed prose development questions over the three non-reserve
PDFs, emphasizing paraphrases, conditions/exceptions and selected multi-document scope.
Compare current final-8 RRF to reranking the same lexical/semantic candidate union
(up to 40 distinct passages), using source text plus necessary context. Do not rerank
only the final 8 when testing selection improvement. Log full candidate/context
identities and page-level relevance; only then consider a few paired generation checks.
Measure relevant/necessary evidence entering the actual context and added wall time,
not merely a reranker score. No new public endpoint or index rebuild is intrinsically
required. New material embedding and any reranker calls require explicit scope/model
approval, quota checks and a bounded time/call budget before execution.

Existing voyageai 0.5.0 exposes Client.rerank, so a hosted Voyage experiment need not
add a runtime package. Production integration still needs provider errors, deadlines,
rate admission, provenance and regression checks. Current embedding-only 3RPM/10KTPM
scheduler must not be assumed to implement reranker limits. Latest public pricing and
limits were checked on 2026-09-27: https://docs.voyageai.com/docs/pricing and
https://docs.voyageai.com/docs/rate-limits. Public table rates are not account-specific
quota verification; free-credit eligibility is not assumed. No experiment, supplier
change or adoption decision was made by this follow-up.


## 后续证据更新

P-035经用户批准已完成正文8题对照，观察到P03排序导致的必要事实缺失及重排改善。本文“不引入”的混合样本判断保留为历史，不外推为正文无收益。当前生产仍RRF，后续判断以m44_prose_comparison.md/json为准；尚无生成对照或上线。
