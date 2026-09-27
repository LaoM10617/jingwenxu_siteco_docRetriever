# M4.2 reliability and experience checkpoint

2026-09-27. Development verification, not a formal benchmark. Base: main
`de8487dd25ce5f21127d59395e965686f0005a42`; changes remain uncommitted.

## Implemented

- Carry previously validated subject identities through chained follow-ups within the existing 6-turn / 12,000-character budget. Reject question-only unresolved phrases for a previously resolved turn; allow literal source topics. Retrieve all evidence anew from the current scope.
- Restore material selection in the same tab/conversation, recheck ready state after loading, explain removed selections and clear on a new conversation. Frozen requests are unchanged; refresh never automatically posts.
- Show observed stage and elapsed time, including quota-wait explanation without an estimated completion time. Setup info distinguishes service health from provider availability.
- Show CSV order number, EAN, original price and date as labelled fields, with all original fields still accessible. No invented currency/unit. Existing PDF source grouping remains unchanged.
- Rename explanatory navigation to Session info / Setup info; configuration remains read-only.

## Verified

The user explicitly authorized two serial real rechecks using the original completed
parents, D01/D06/D09 scope and existing Gemini/Voyage configuration. Both were used,
without retries, uploads, provider changes or paid-tier changes:

- M41-06: 3.157 seconds end to end. Resolved and queried `0MD5307L0940`, returned `exact_not_found` in the selected CSV with zero records/citations. This repairs the observed wrong lookup key; the original M4.1 failure remains recorded.
- M41-03: 4.219 seconds. Resolved `51DB11EC11B1D`, answered `01.06.2026` from CSV logical record 1.

Provider logs contain five Gemini calls (2 + 3), no Voyage events, no observed retries
or provider errors. These are task wall times, not precise internal retrieval timings.

- Related backend task/memory/scope tests: 34 passed (12.29 s). After clarifying a test question, memory subset: 18 passed (5.58 s).
- TypeScript/Vite build succeeded. Full frontend suite against rebuilt Docker: 29 passed, 12 opt-in skipped (27.1 s). Full backend/Linux suites were not rerun; older 308-test results are historical.
- GET-only browser replays restored cross-scope and date conversations and retained selection after refresh; zero write requests. Desktop and 390px mobile CSV sources were visually checked; mobile had no horizontal overflow.
- Running backend matches all 23 workspace Python source files by SHA256; three documents ready and both recheck tasks completed. Docker uses the existing runtime and ports 18094/18095. Temporary Vite 18096 stopped.

Local raw evidence: `tmp/m42-validation` (requests/results, provider metadata,
`browser-check.json`, desktop/mobile screenshots, `final-check.json`). Earlier failure
artifacts remain in `tmp/m41-live-20260927`; see [M4.1](m41_development.md).

## Limits and next step

Identity provenance is not semantic correctness. Conservative clarification can reject
question-only references, and free-text product attribution remains a model risk.
No general accuracy rate, stable latency percentile, new-upload timing or PDF ranking
claim follows from these two samples. No held-out questions were used. Health checks
do not validate provider keys/quota. Original-page preview/highlighting, editable
provider settings and formal evaluation remain later work.

M4.2 is complete within the agreed scope. Next: M4.3 preview/highlighting, first confirm
its public interface and evidence-position contract. The two-call authorization is
exhausted; additional live calls need an expanded authorization.
