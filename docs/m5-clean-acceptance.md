# M5 clean-runtime acceptance proposal

2026-09-27. User approved delivery preparation and clean-runtime acceptance work.
Source baseline: 29a1d9e (period fix); the documentation candidate commit will be
recorded in the execution receipt. Live provider calls below await explicit budget
approval under P-040/P-041. No change to retrieval, prompt, model or scoring rules.

## Isolation and no-provider preparation

Export the committed tree to tmp/m5-delivery/source; preserve Git history in the
actual repository. Use Compose project siteco-m5-delivery, backend port 18104,
frontend port 18105 and empty tmp/m5-delivery/runtime. Build both images, prepare
the public pinned tokenizer using README instructions, start services and verify
health, empty Materials, and visible missing-credential behavior. Do not reuse
existing database, vectors, answers or tokenizer files. Cached Docker dependency
layers are permitted and explicitly recorded. Existing siteco-m28-smoke is untouched.

## Proposed live scope: nine turns

Use exactly the full terms PDF (4 pages), privacy PDF (12 pages), Rondel PDF (2 pages)
and full 11,386-row price CSV from eval/cases/m50_protocol.json, with matching hashes.
All are previously seen materials. This is acceptance/regression, not a new holdout
benchmark. Model: Gemini gemini-3.5-flash-lite; Voyage voyage-4/1024; RRF Top K 8;
rerank off. Local admission: 60 RPM, 200000 TPM, 1-second minimum interval (previously
approved local profile); no account/payment changes. Keys loaded only for the new
backend runtime; no key values in logs, screenshots or receipts.

Use original questions and reference evidence from docs/m50-casebook.md:

1. E01: terms payment conditions; check evidence and omission/qualification behavior.
2. E02: privacy retention in two sections; check attribution against both sections.
3. E03: compare the two Rondel orders; inspect the original product table.
4. E04: same conversation, second luminaire follow-up; verify resolved subject.
5. E05: same conversation, select only CSV; verify no PDF evidence leaks into answer.
6. E07: new conversation, price/EAN comparison ending in a period; exact two orders.
7. E08: new conversation, synthetic absent order; explicit exact miss, no substitute.
8. E09: new conversation, terms+CSV mixed scope; supported fact plus explicit miss.
9. E12: new conversation, two CSV final-row orders ending in a period; price/date.

Except E03-E05, each question starts a new conversation. If a chain fails, its
remaining dependent turns are recorded blocked, never fabricated. Inspect sources,
refresh a completed conversation to verify GET-only recovery, and check failure
feedback without intentionally sending invalid credentials to providers.

## Requested new budget and stop conditions

At most 64 provider attempts total: document embedding <=24, query embedding <=8,
generation <=32, rerank/Groq =0. Estimated-cost control USD2 maximum using the prior
protocol's conservative token accounting; not a statement of invoiced charges.
No automatic/manual retries, connectivity probes, alternate models or extra turns.
Stop before exceeding a category/total/cost cap; preserve all failures. If a provider
failure or validation issue blocks continuation, stop affected work and report it.
Expected hands-on runtime after successful build: roughly 30-60 minutes, dependent
on providers and inspection; this is not an SLA. Preparation has no inference cost.

## Evidence and acceptance

Record commit, configuration, Docker image IDs, material hashes, empty initial state,
first-attempt outcomes, source/page/record checks and screenshots without credentials.
Use passed/failed/blocked/not-run, and distinguish operational path success from
answer correctness. Do not overwrite run-20260927-ab-01 or reuse its aggregate score.
Persistent wrong answers remain explicit quality limitations even when containers
and UI work. Final release requires a separate reviewed decision after these results.
