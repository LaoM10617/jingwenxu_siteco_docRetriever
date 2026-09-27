# M4.1 development quality and timing check

2026-09-27. Development investigation only; not the frozen M5.0 benchmark.
Production baseline: `de8487dd25ce5f21127d59395e965686f0005a42`. All 23 running
backend Python files matched the workspace by SHA256. No production code,
retrieval parameters, model configuration or containers changed during this run.
Inherited uncommitted handoff/README changes remain intact.

## Scope and method

The user directly authorized D01/D06/D09 evidence, eight development turns and
one additional cache observation to Gemini `gemini-3.5-flash-lite`, with authorized
PDF/query embedding through Voyage-4. No holdout, other receiver or paid-plan change.
Three original material hashes matched `eval/material_manifest.json`. Terms page 1
and Rondel page 2 were visually checked using existing renders; the first CSV logical
record and exact absence of both test lookup IDs were checked locally.

[Fixed cases](../cases/m41_development.json) were saved before the first POST.
[Runner](../check_m41_development.py) uses the existing task HTTP API, one POST per
case, one-second GET polling, and a 20-second pause between completed questions.
Parents remain in the same conversation; independent first turns use new conversations.
It stops on execution/client failure and does not retry an answer-quality failure.
Its process exit is a collection result, not a semantic-quality pass.

Command actually executed:

```powershell
& ./backend/.venv/Scripts/python.exe eval/check_m41_development.py --run tmp/m41-live-20260927 --authorized
```

This is an outbound command: do not rerun merely to inspect results. The directory
must be new, and authorization must cover the fixed cases and configured providers.
The flag documents an operator decision; it does not confer authorization itself.
Full requests, task IDs, answers, citations, memory references and stage observations
are retained in the ignored `tmp/m41-live-20260927/` directory. The versionable
[summary](m41_development.json) contains per-case timing and manual verdicts.

## Per-turn evidence review

1. **M41-01 / D01, 3.203 s:** Incoterms 2020, terms physical page 1 / Article II.3.
   Fact supported. Outcome partial because 7 of 8 retrieved passages entered the
   context, with one omitted; this is not a wrong factual answer.
2. **M41-02 / D09, 3.172 s:** exact order 51DB11EC11B1D, price 183,20 and date
   01.06.2026, CSV logical record 1. No invented currency, tax or discount.
3. **M41-03, 4.234 s:** date follow-up resolves 51DB11EC11B1D and retrieves current
   CSV record 1 again; answer 01.06.2026 is supported.
4. **M41-04 / D06, 3.156 s:** both model rows correctly assigned: 0MD5307L1830 =
   3000 K / 1800 lm / 18 W / ON-OFF / 1.6 kg; 0MD5307L0940 = 4000 K / 900 lm /
   9 W / ON-OFF / 1.6 kg. Source is Rondel physical page 2. Layout warning retained.
5. **M41-05, 3.172 s:** “second luminaire” resolves to 0MD5307L0940 and returns
   4000 K / 9 W from the current PDF scope. The historical ordinal-generation
   mistake did not recur in this particular turn.
6. **M41-06, 3.188 s — FAILED subject identity:** following M41-05, scope changes
   to CSV only. The expected product remains 0MD5307L0940. Actual memory resolves
   the literal phrase `the second luminaire`, and planning submits that phrase as
   an exact order key. The task reports exact_not_found with zero records. It did
   not reuse the old PDF's 9 W, but searched the wrong identity. Even though the
   intended product is also absent from this CSV, matching the final absence
   outcome does not make the reasoning/query correct. No answer-generation call
   occurred after the empty lookup. This is a resolution/planning semantic failure,
   not a PDF parsing failure, vector-ranking failure or provider execution error.
7. **M41-07, 4.219 s:** mixed terms+CSV scope returns Incoterms 2020 with the correct
   source, and separately discloses the exact miss for 51DB11EC11B1D-NOT-FOUND.
   It does not substitute the real 183,20 price. Supported partial outcome.
8. **M41-08, 3.203 s:** supplier terms do not apply automatically; the purchaser
   must have expressly agreed in writing, and applicability remains “insofar as”.
   Both the scope and condition are preserved, supported by Article II.1 / page 1.
9. **M41-09-cache, 2.219 s:** exact repeat of M41-01 with identical selected scope
   in a new conversation; supported 2020 answer. Additional cache observation,
   excluded from the primary eight-turn median and not an independent quality case.

Manual review found the requested facts/behavior supported in seven primary turns
and a semantic query failure in M41-06. This is a description of these development
observations, not an accuracy estimate. Related conversation turns are not
statistically independent. No fresh scan/OCR, duplicate-source, provider-fault or
large-history matrix was attempted; historical controlled evidence is separate.

## Failure evidence and M4.2 priorities

**F1 — first: carry the actual product through chained and changed-scope follow-ups.**
The saved `subject-check.json` compares expected 0MD5307L0940 against both returned
references and lookup order IDs and fails deterministically. It is a replay check
of this observed artifact, not proof that every fresh model call fails.
The browser GET-only replay visibly shows “Subjects resolved … the second luminaire”
and “No exact match: the second luminaire”.

The recorded chain rules out a correct resolved ID being changed only in the final
answer: the wrong phrase is already present in memory and the lookup, and there is
no final generation step. Both parent task IDs are present in history. Code currently
allows literal subject phrases from historical questions/sources and checks literal
occurrence, not that a phrase has become a stable product identifier; planning then
accepts a literal key found in the resolved question. This explains the observed
acceptance path, not the stochastic reason the model selected the phrase.

M4.2 should first lock this case into the already approved memory/task test boundary,
then examine chained reference normalization and the CSV planning guard. Preserve
support for legitimate non-product topic phrases; do not reject all natural language
or use a SITECO-specific order-number regex as a general fix. If a subject cannot be
reliably resolved, explicit clarification is preferable to a confident lookup of an
unresolved pronoun phrase. Concrete implementation remains M4.2 work.

**F2 — next: restore and revalidate selected materials after refresh.**
A headless Edge replay seeded only these three completed tasks and blocked every
non-GET API request. It restored 3 turns, selected the CSV, reloaded, then observed
0 selected materials. No blocked writes and no page errors occurred. Screenshots and
`browser-observation.json` retain the evidence. No new model calls were needed.

**Then follow the agreed experience work:** make resolved model/parameters and
source fields easy to compare; distinguish context omission from a missing answer
fact; improve elapsed/stage explanations and label History/Settings accurately.
Do not change the partial-outcome contract without considering its existing meaning.
No new ranking evidence justifies adding a reranker now; M4.4 still owns that decision.

## Timing and provider observations

The primary eight client durations range from 3.156 to 4.234 s; median 3.1955 s.
These include POST/polling and up to approximately one second of terminal polling
lag. Inter-question 20-second pauses are not included in per-question latency.
Provider logs show 15 successful generation/resolve/plan calls and 5 successful
Voyage query calls over all nine tasks, with no logged provider error or observed
quota-wait stage. Per-case provider durations are in the JSON summary.

M41-01 includes a Voyage query call (0.470 s); the identical M41-09 query has no
Voyage event while generation still runs (1.549 s). With unchanged code/configuration
and the backend's query cache path, this supports cache reuse. It does not isolate
all latency variance: generation durations and polling alignment also differ.
No general speedup ratio or stable P95 is claimed, and this short run does not
invalidate historical 82-second quota waits.

Existing ready documents were reused. No new upload/ingestion duration was measured;
prior ingestion measurements remain historical. No live SQLite was opened externally.

## Instrumentation limits and validation

The original collector mistakenly required the logger name `siteco.providers`, but
its StreamHandler emits plain messages. Original per-case JSON therefore has empty
provider_events arrays. Metadata was recovered from retained Docker logs using each
case's saved UTC start/end window into `provider-events-recovered.json`; originals
were not rewritten and no question was resubmitted. The runner filter is corrected
for future runs. Attribution is by serial time windows, not request IDs; competing
model requests would weaken it.

The public result provides cited sources, route counts, context counts and CSV query
metadata, but not every ranked/omitted PDF passage. Therefore this run cannot compute
Evidence Recall@8 or precisely audit every retrieval candidate. Do not treat missing
full tracing as a retrieval miss. For M5.0, capture rankings/context through a bounded
evaluation harness at the existing internal retrieval boundary after settling the
measurement contract; a new public API is not automatically required.

Exact queue/retrieval CPU times were not measured; provider-time subtraction is not
an exact stage measurement. Full model wire payloads were not captured. Stage samples
and metadata logs are the available evidence. The run validates subject/output/source
behavior, not a new exhaustive semantic validator.

Checks performed: material/source hashes, original-page/record checks, nine complete
HTTP task records, citation scope checks, deterministic negative subject check,
GET-only browser recovery/selection observation, Python syntax and diff checks.
No full backend/browser suite was rerun, because production code was unchanged.
M4.1 is complete with findings; M4.2 fixes, feature freeze and M5.0 remain incomplete.
