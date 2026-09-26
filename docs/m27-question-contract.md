# M2.7 question, tool and evidence contract

Approved direction: P-028. Baseline a00f896c489c2bdbb6d8b197b2e006166ea727aa.
Steps 1–6 implement the internal question/answer core. Task HTTP and UI follow in
M2.8; this is not the Docker/browser end-to-end completion of M2.

## T-008: QuestionTools.prepare

Input: conversation_id, question (1–8000 nonblank characters), explicit document_ids
(1–10). Unknown fields/types are rejected. Validate the complete ready scope before
any provider call; deduplicate document IDs in request order. Every invocation owns
its evidence bundle, with no global conversation history or reusable S1 namespace.
Each request freezes its scope. A conversation identifier does not grant access to
documents. No multi-turn resolution or persistent conversations in this increment.

prepare(request, planner=None, budget=None) validates a bounded plan then executes
at most one PDF retrieval and one CSV exact lookup. With PDF-only scope, the default
is direct retrieval. CSV/mixed scope needs the injected planner's structured plan;
AnswerService supplies the real LLM planner adapter. No heuristic order extraction
is substituted for the model. The planner receives only this validated question,
document metadata and its deadline, never another conversation's history.

Plan: tools is a strict discriminated union of retrieve_pdf(document_ids) and
lookup_orders(document_ids, order_ids). At most two tools, no duplicate route,
1–50 nonblank string order IDs (max 200 characters). IDs must be literal tokens
present in the question. All tool ranges are validated before the first execution.
No raw SQL, Python, unknown fields, coercion, fuzzy fallback, query expansion or
recursive tool loop. An empty plan yields needs_clarification, not not_found.
The PDF query is the original question. Actual queried scopes are returned.
Each invoked route must cover all selected documents of that type; the model may
choose a route but cannot silently narrow its same-type scope. An uninvoked route
does not supply evidence and cannot establish a miss in that document type.

Execution produces an evidence bundle, NOT a generated answer: tool results,
route outcomes, document warnings, unresolved reasons, and question-local S1… IDs
mapping to the complete original source objects. CSV takes first 50 records with
full counts/unmatched IDs/has_more; this is explicitly not a full-result summary.
Missing order IDs in CSV-only planning yield clarification. An exact miss never
initiates an unplanned PDF search. Mixed independent routes retain separate outcomes.

## T-009: evidence-bound deterministic tools

Facts are derived from this bundle, never accepted as caller-supplied numeric
operands. CSV Listenpreis comes from valid stored Decimal strings and raw cells;
currency is unknown and never inferred. PDF proposals identify a source span,
product and whitelisted parameter. Only an explicit self-contained labeled
statement whose entire span binds product/parameter/value/unit is initially
eligible for numeric execution. Other tables/prose remain available as evidence,
with an explicit unverified-relationship result, not silently discarded or guessed.
This conservative gate is not a general semantic verifier; broader relationship
grammars require corresponding evidence and tests, not document-specific hacks.
The first gate requires exactly one source span and no separate context; otherwise
it returns unverified_context so external qualifiers are never silently ignored.
The explicit form is `PRODUCT LABEL: NUMBER UNIT` with optional `(qualifier)`.
Different raw labels (e.g. rated power vs Systemleistung) are not assumed equivalent.
Dot/comma decimals are accepted without grouping; ambiguous nonzero 1–3 digit
integers followed by a separator and exactly three digits are rejected. No exponent,
NaN, Infinity or inferred locale. Raw value is retained independently. This is a
safe initial calculation subset, not completion of all PDF parameter questions.

Parameters: price, power, length, mass, luminous_flux, color_temperature.
Units: W/kW, mm/cm/m, g/kg; lm and K only within their own dimension.
Operators: eq/ne/lt/le/gt/ge. Conversion uses finite Decimal strings and exact
powers of ten, with adequate local precision (no float/implicit rounding).
Comparisons require the same parameter, raw label and qualifiers. Price validity
(`gültig ab`) is retained as a qualifier. Price comparisons state
numeric-only semantics and require the same source document (no currency inference).
Return original value/unit/source, converted value and exact factor/basis.
Unverified PDF facts, missing/invalid prices, unsupported units and mismatched
qualifiers are explicit unavailable results, never false comparisons or zero.

## Result and time semantics

Final JSON distinguishes execution running/completed/failed from answer
answered/partial/needs_clarification/insufficient_evidence/exact_not_found.
Partial answers show verified information AND the missing/ambiguous information;
source existence alone never proves an assertion. Invalid citations cannot certify
a claim. Provider errors/timeouts are execution failures, not absence of evidence.

QuestionBudget uses a monotonic 240-second deadline shared by all steps. Checks
before/after external calls discard late results; stop is cooperative, not a forced
termination of a blocking provider. Embedding quota limits stay unchanged; request
stop and waiting callbacks pass through retrieval. At most 180s per admission, also
bounded by question expiry. Provider adapters must honor remaining time; no deadline
reset on retries. Generation calls use min(60s, remaining question time), discard
late results and do not automatically retry. Task terminal-state publication follows
in M2.8. 202 + 1–2s polling and final complete JSON are
approved; SSE/token streaming remain deferred. nginx read timeout is an idle-read
timeout, not an overall request duration.

## Verification

Tests cross T-008/T-009 with real temporary DocumentService/SQLite publication,
synthetic PDF/CSV and controlled external planner/embedding providers and clocks.
Cover full-scope gating, conversation isolation, schema/range validation, literal
order IDs, duplicates/paging/misses, evidence identity/context/warnings, decimal
precision, ambiguous PDF relationships, incompatible units and late results.
These controlled tests do not use live providers or production databases. Separate
opt-in development-only real checks and failures are in eval/results/m27_answers.md.

## Internal generation and answer publication

AnswerService.answer(request, budget=None, on_wait=None) composes T-008/T-009 and
StructuredModel.generate(system, payload, schema, budget). PDF-only scope needs no
model routing; CSV/mixed scope uses the strict ToolPlan. No evidence means no answer
generation: exact_not_found, needs_clarification or insufficient_evidence is returned.
No other conversation history is sent. Construction at app startup makes no calls.

Model Draft contains outcome, segments, gaps and calculations. Each segment has
text, citation_ids and calculation_ids; no model-provided filename/page/record.
At most 20 segments (4000 characters each), 20 citations per segment, 10 gaps and
10 calculation proposals. Proposals contain only a unique calculation_id plus the
existing compare/convert union. One bounded calculation round executes T-009 and
then asks for a final Draft with calculations empty. At most three model calls for
CSV/mixed questions, two for PDF-only questions; no repair/retry/fallback loop.
Unavailable calculations preserve the evidence and require a partial answer/gap.

Context includes whole source objects with original text, source spans, headers,
qualifiers and locations, never truncated within an evidence record. Initial budget
is 28000 serialized evidence characters; over-budget records are omitted and counted.
All tool totals/unmatched IDs/has_more are retained; warnings shown to the model are
the first 20 with full count. The final result retains all document warnings.
These are implementation limits, not tuned retrieval parameters. Models must state
pagination limits and cannot claim a summary of records they did not see.

Citation publication resolves only short IDs actually supplied to this generation,
requires membership in the frozen scope, then calls DocumentService.read_evidence_id
with (document_id, evidence_id). CSV uses an indexed exact query; PDF resolves the
published in-memory evidence without walking HTTP pages. The source must still be
ready and match original text/locator/raw values/context/spans. A failed citation
rejects its whole segment, not just its marker. Remaining valid segments yield
partial; all segments rejected yields generation_invalid_citations. Successful
calculation references must include all operand citations. Final citations are
backend-generated source objects. Referential validation is not a semantic proof
that the text entails every claim; real answer checks remain necessary.

Success returns status=completed, outcome, conversation_id, document_ids, segments,
citations, gaps, calculations, warnings, unresolved, tool_results, context counts,
provider/model and validation.rejected_segments. Provider/schema/citation failures
raise DocumentError for the future task owner to publish as failed. Authentication,
quota, transport/unavailable, timeout, refusal, truncation and malformed output have
distinct sanitized codes; raw provider exceptions and keys are never returned.

Official google-genai and groq SDKs perform complete JSON requests without tools or
streaming. The provider-facing schema is a conservative projection; strict Pydantic
validation is authoritative. SDK retries are disabled; provider changes are explicit.
HTTP timeout bounds socket phases, not a hard wall-clock thread kill. The adapter
also rejects results arriving after its per-call deadline. SDK research and exact
versions are recorded in docs/m27-generation-notes.md.

Controlled validation covers whole-segment rejection, real but unprovided IDs,
duplicate uploads, source lookup, pagination/context limits, numeric finalization,
late output, malicious source instructions and arbitrary operations, using real
temporary storage. Both actual SDKs are exercised through controlled HTTP transports
for request shape, finish reasons, errors and no retries. Real provider acceptance
is separate and does not establish all-question accuracy or a latency SLA.
