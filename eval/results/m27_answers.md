# M2.7 answer and citation checks

2026-09-26; base a00f896c489c2bdbb6d8b197b2e006166ea727aa plus current uncommitted
M2.7 work. This verifies the internal answer core, not M2.8 HTTP/UI or M2.9 browser
completion. The user explicitly authorized Gemini + Voyage development acceptance
for D01/D06/D09. No holdout question was executed or used for tuning; no paid-plan
switch or automatic provider fallback occurred.

## Controlled verification

- Windows: 255 tests + 10 subtests passed (41.87s).
- Linux Docker: the same 255 + 10 subtests passed (35.10s), image
  siteco-backend:m27-answer-test built with the locked dependencies.
- Both SDK adapters ran over controlled HTTP transports, including authentication,
  quota/unavailable, invalid JSON, truncation, late output and no-retry checks.
- Real temporary SQLite/PDF/CSV tests cover invalid/unprovided/duplicate-upload
  citations, whole-segment rejection, partial/all-invalid publication, full CSV
  totals versus bounded context, deterministic calculation results and source lookup.
- Existing ready data and preview containers were not replaced. Keys/materials are
  excluded from the Docker context by its allowlist.

## Real development checks

Model: gemini-3.5-flash-lite through google-genai 2.25.0. PDF embeddings: Voyage-4,
1024 dimensions, existing shared 3RPM/10KTPM scheduler. All calls serial in isolated
D-drive runtimes; original material hashes checked against material_manifest.json.
Each source is re-resolved by the backend before returning the answer.

**D09 CSV** — successful run returned: “Für das Produkt mit der Bestellnummer
51DB11EC11B1D beträgt der Listenpreis 183,20 und das Gültigkeitsdatum (gültig ab)
ist der 01.06.2026.” S1 resolves to logical record 1, retaining original fields;
total=1, has_more=false. No inferred currency/tax/discount. Upload-to-ready 0.343s,
answer 4.110s (planning plus generation). Outcome answered.

Failure retained: the first real D09 run produced an empty plan and thus
needs_clarification in 1.984s, despite the explicit order ID. It is an answer-quality
failure, not a passing check. Local SDK capture showed the correct question and full
union schema on the wire; an unchanged second execution succeeded. No root cause
or reliability fix is claimed. The harness now fails on empty answers and preserves
model output; production does not automatically retry this outcome. This small
sample cannot establish stable routing accuracy.

**D01 procurement terms** — returned “Für Incoterms ist der Stand von 2020
maßgeblich.” S1 maps to physical page 1, Article II.3 in its surrounding clause
block. Original page was visually checked. Backend outcome partial because the
28000-character context budget supplied 7 of 8 retrieved candidates; the direct
answer is supported, but omitted context remains explicitly counted. No invented
exception or legal conclusion. Upload-to-ready 41.500s; answer 82.672s; generation
itself 2.328s. This is not a full legal-conditions/exception reasoning benchmark.

**D06 Rondel parameters** — two separate segments, both citing page 2 S1:
- 0MD5307L1830: 3.000 K, 1.800 lm, 18 W, ON/OFF, 1,6 kg.
- 0MD5307L0940: 4.000 K, 900 lm, 9 W, ON/OFF, 1,6 kg.

Both rows and column headings were visually checked on the original page. Outcome
answered; all 8 candidates fit the context. The original layout_uncertain warning
remains in the answer. This is a source-backed side-by-side listing, not a numerical
difference/ratio calculation; calculations is empty. The narrow PDF deterministic
calculation gate was not broadened to infer table relationships. Upload-to-ready
18.985s, answer 20.937s, generation 2.250s.

## Latency and limitations

Six successful Voyage calls were recorded: D01 document batches 3411/3431/492 tokens,
D01 query 21, D06 document 980, D06 query 31 (8366 successful usage tokens total).
Successful call durations were 0.234–1.515s; starts were at least 20s apart. The
initial recorder recorded successes only, so six must not be called the total
attempt count. D01's query start had an 80.61s gap after the last document batch.
After service.stop and process exit, a read-only inspection of this isolated runtime's
quota tables confirmed a persisted provider-retry cooldown ending immediately before
the successful query admission. The original error code/failed attempt duration was
not captured; do not assert specifically 429 or attribute the whole delay to local
3RPM waiting. The harness now records failed attempts/cooldown hints and emits
ingestion and query waiting states; this logging change makes no provider-policy change.

Across these runs Gemini made five successful API calls: one failed-quality plan,
then D09 plan+answer and two PDF answers. No Groq live-data call. Full ignored local
reports: tmp/m27-gemini-csv/answer-results.json (failure),
tmp/m27-gemini-csv-v2/answer-results.json and tmp/m27-gemini-pdf/answer-results.json.
They retain returned sources and model responses; no credentials. PDF visual checks:
tmp/m27-visual/terms-page-1.png and tmp/m26-acceptance/rondel-page-2.png.

Question deadline remains 240s; one generation call min(60s, remaining). Keep cached
ready documents and query priority; do not re-embed on restart. M2.8 must expose real
waiting/failed states with 202 + polling, and ensure late workers cannot overwrite a
terminal timeout. These timings are small development samples, not an SLA. Referential
citation validation does not mechanically prove all generated claims. Final Docker
browser new-upload-to-answer and Standards/Spec review are still required for M2.
