# M3.5 integration checkpoint

2026-09-27. Baseline and HEAD: 88ad778baf6b272ccd8151e67f6801e767dce24d.
All M3 changes are uncommitted. Initial dual review: Standards found one stale-status
documentation issue (fixed); Spec found none. Final closing review is recorded in
m3_checkpoint.md and the final snapshot receipt.
No new commit or push was made. The inherited six M2.9 closing documents remain included.

## Controlled matrix

Final production code: Windows 308 passed + 10 subtests (60.00s); Linux test-image
build siteco-backend:m35-test: 308 + 10 (49.05s). These include the M3.1 multi-document
matrix, M3.2 status/queue boundary, M3.3 business/source cases, M3.4 failure/recovery,
and P-031 memory plus the new explicit resolved-subject provider-boundary regression.

Static Docker frontend: 28 passed / 6 historical opt-in skipped (26.5s), including the
actual nginx proxy check. Added M3 real scenarios are explicitly opt-in. Frontend
TypeScript/Vite and both runtime images build successfully. Image metadata/history
and static assets contain none of the supplied key values; the frontend has no
provider-key environment variables. git diff --check passes.

## Runtime and authorized live checks

The existing siteco-m28-smoke backend/frontend were rebuilt at 18094/18095, retaining
D:/Projects/Retrieval_SITECO/tmp/m28-clean/runtime. No database/index copying or
external access to running SQLite. Original Rondel and CSV ready documents survived.
This is an upgrade/integration run, not another empty-runtime M2 demonstration.
The D01 procurement PDF was newly uploaded through the browser and became ready:
f1338ce4cdc44f7d82e1ce5232e590ef. D06 and D09 retain the IDs in the M2.8 report.
Other old ports/runtimes were not changed. Only two resident services remain.

Six new questions total were submitted serially using only D01/D06/D09 development
materials (including a synthetic missing key derived from D09). No holdout, OCR,
vision, paid-plan switch, or new outbound material. Gemini remains
 gemini-3.5-flash-lite; Voyage remains voyage-4/1024 with shared scheduling unchanged.

Initial four-question browser sequence:

1. All three documents selected: Incoterms 2020 plus CSV 51DB11EC11B1D price 183,20.
   Correct separate citations to terms physical page 1 and CSV logical record 1.
   Partial outcome correctly discloses one omitted passage. 82.219s; a real Voyage
   embedding_rate_limited event returned retry_after=60, then the existing scheduler
   recovered. Health and polling stayed responsive; quota wait was visible.
2. After refresh, scope changed to CSV only: a pronoun-based date question resolved
   51DB11EC11B1D and returned 01.06.2026 from a fresh CSV lookup. 4.202s.
3. New conversation, PDF+CSV: separately listed 0MD5307L1830 = 3000 K / 18 W and
   0MD5307L0940 = 4000 K / 9 W. Synthetic 51DB11EC11B1D-NOT-FOUND returned zero exact
   CSV records with an explicit gap; PDF parameters did not masquerade as a match.
   Partial outcome. 13.502s. Original Rondel page 2 was visually checked.
4. PDF-only follow-up asking about the second luminaire: resolution correctly chose
   0MD5307L0940, but generation reinterpreted the ordinal using table row order and
   answered 0MD5307L1830 / 3000 K / 18 W. 18.862s. This was a genuine quality failure,
   despite valid citations, and the browser assertions failed. It is not counted as
   a pass. Full report retained at tmp/m35/real-results-initial-failure.json.

## Fix and bounded revalidation

Planning and answer generation now receive validated resolved_subjects separately.
The shared instruction binds pronouns/ordinals to these subjects and forbids
reinterpreting them by counting retrieved rows. No model-written arbitrary question
rewrite, new evidence source, or wider scope was introduced. A task-HTTP test first
failed on the missing provider-boundary context, then passed after the fix; 48 related
checks passed before the final full Windows/Linux runs above.

Only the two original follow-ups were submitted again after backend rebuild, each
using its original completed parent and unchanged question. Both answer assertions
passed: CSV 01.06.2026; PDF 0MD5307L0940 / 4000 K / 9 W, with only current-scope citations.
The two test cases later failed at refresh because their setup script overwrote
sessionStorage on every load. That fixture was corrected to seed once. Two separate
GET-only browser tests then restored both retained parent/child pairs, refreshed,
and verified zero POSTs (2 passed, 2.1s), without extra provider calls. Do not describe
the original full four-question test or the uncorrected replay harness as passing.
Reports/screenshots: tmp/m35/fix-validation/. The initial failure remains retained.

After rebuild, logs record five successful Gemini calls for those two follow-ups
(resolve/plan/answer and resolve/answer), and no new Voyage calls (query cache reused).
Initial ingestion logged three successful Voyage batches, 3411/3431/492 tokens;
one query rate-limit event was captured. Complete initial provider logs were not
archived before recreation, so no precise overall provider-attempt count is claimed.

## Acceptance limits

The controlled matrix checks execution failures, terminal immutability, queue limits,
expiry and lifecycle restart interruption; this run does not claim a Docker hard-kill
fault-injection matrix. Completed parents remained usable after the real rebuild.
The small real sample does not establish planning/reference-resolution reliability.
Literal source identity is not semantic entailment; prompt binding reduces this
observed ordinal error but is not a deterministic proof against future wrong prose.
PDF layout warnings, retrieval noise and synchronous provider worker occupancy remain.
Final Standards/Spec reports and fixed hashes are recorded with the M3 review snapshot.
