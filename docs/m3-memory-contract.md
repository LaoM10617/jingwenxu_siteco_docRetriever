# M3 temporary conversation memory contract

P-031, confirmed 2026-09-27. M3 review baseline: 88ad778baf6b272ccd8151e67f6801e767dce24d.
This extends the M2.8 contract; it does not add a service, dependency or authentication.

## Request and retention

POST /api/questions accepts optional previous_question_id. Omission preserves an
independent question. A supplied parent must exist, belong to the same conversation,
be completed, and be within retention; otherwise admission returns a structured 409
(memory_unavailable, memory_expired or memory_not_completed), before model calls.
The parent is immutable request content: changing it under the same request_id is 409
request_conflict. Concurrent API clients may explicitly branch from the same parent.

All tasks in a conversation share conversation_expires_at, fixed 86400 seconds after
its first retained root was submitted. A follow-up never extends it. Expired task GET
and CSV paging return 404; terminal rows are removed by the existing monitor/admission
cleanup. Ready documents remain available. Expired parent IDs cannot silently create
new memory. Without a parent, a fully expired conversation ID can be reused as an
independent request after cleanup, consistent with temporary idempotency; the browser
requires an explicit new conversation with a new ID instead.

SQLite adds a conversation_expires column in the backend's startup transaction.
Legacy rows use the earliest retained creation time for their conversation; previously
purged history cannot be reconstructed. Completed results remain readable and same-ID
recovery remains valid. No running database is read by an external process.

## Resolution and evidence

Follow parent links, most recent first, taking at most 6 whole turns and a total of
12000 characters measured as the sum of their JSON serializations (ensure_ascii=False).
A turn contains its ID, original question, published answer segment texts, gaps and
published citation source texts and previously validated resolved_subjects (identity
clues, not facts), all counted within the same budget. Stop at the first turn that would exceed the budget;
never cut away qualifiers or skip a nearer turn to include an older one. Send the
selected turns chronologically. If none fit, return a clarification without a model call.

One structured model call (stage resolving_references) selects references as
{question_id, term}, at most 10 terms of 200 characters, or requests clarification.
History is untrusted input. A self-contained question may use no reference terms.
For a turn without prior resolved subjects, every term must match a complete literal
item in its question or published source text, using the existing word/model boundaries.
For a previously resolved turn, accept an exact retained subject or a complete literal
source item; question-only phrases such as "the second luminaire" require clarification.
Source topics remain eligible. This conservative guard may clarify a reference that
exists only in the original question; it does not automatically select a sole subject.
Historical answer prose alone cannot authorize a new exact lookup identifier.
Unknown IDs, invented terms, substrings or declared ambiguity lead to clarification.
Malformed output and provider failures remain task failures, not insufficient evidence.

The original question is preserved and validated reference terms are appended as
conversational subjects, not facts. An arbitrary model-written replacement question
is never executed. If the combined question exceeds the existing 8000-character limit,
request clarification. The resulting question goes through the existing plan schema,
all-selected-type scope checks, exact CSV lookup, PDF retrieval, numeric and citation
gates. Historical sources/citation IDs are never inserted into the new evidence bundle.
Planning and answer generation receive resolved_subjects separately: these bind conversational
pronouns/ordinals and must not be reinterpreted by counting rows in retrieved evidence.
The new answer includes memory.history_question_ids, references, and resolved_question
when resolution succeeds. The UI displays resolved subjects so users can check them.

The same 240-second budget covers queueing, resolution, retrieval, generation and
validation. Late resolution cannot overwrite a timeout. Restart never replays work.
Literal provenance is not a guarantee that the model resolved the user's intention
correctly, or that arbitrary generated prose is semantically correct.

## Browser and verification

The browser attaches the latest completed question, not a running/failed one. It saves
per-tab request metadata, parent links, expiry and local submission time. Material
selection is separately stored for the same conversation, revalidated against ready
documents after loading, and cleared on a new conversation. Invalid selections show
a notice. Existing submitted scopes remain immutable. Refresh reloads task results by
GET; an ambiguous POST requires explicit retry with the identical body and request ID.
Unresolved submissions block sending a new follow-up until recovered or a new
conversation is started. At expiry, sending is disabled and an explicit notice appears.
Switching selected documents preserves subjects but changes only the next turn's scope.

Accepted seams: real SQLite/task HTTP; controlled model, embedding and clocks;
browser linkage/refresh/expiry. backend/tests/test_conversation_memory.py covers CSV
and PDF fresh scope after reference resolution, restart, frozen retry, isolation,
parent state, whole-turn/6-turn bounds, fixed expiry, provider/JSON failures, late
resolution and legacy storage migration. Browser tests cover refresh, changed scope,
expiry and ambiguous follow-up recovery. M3.5 sampled real D01/D06/D09 combinations and retained an ordinal-generation failure
and its bounded repair/revalidation; see eval/results/m35_integration.md. This is not
a general reliability estimate. No held-out question was used for tuning.

M4.2 regression and sampled real verification: [checkpoint](../eval/results/m42_experience.md).
No public request/result schema was added for these repairs.
