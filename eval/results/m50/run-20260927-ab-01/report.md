# M5.0 evaluation: first frozen A+B run

Product `7811243`; evaluation `859447f`. Run `run-20260927-ab-01`.

A+B execution completed in 260.9 seconds using 33 provider attempts. C was not authorized and did not run.

Strict pass: 3/12; required facts and supported cited facts: 10/40. Completed tasks: 6; failed tasks: 4; dependent blocked turns: 2.

## Retrieval comparison

- lexical: evidence 9/12; macro recall 0.8929; complete 6/7; MRR@8 0.8929; post-context evidence 9/12.
- vector: evidence 12/12; macro recall 1.0000; complete 7/7; MRR@8 1.0000; post-context evidence 12/12.
- rrf: evidence 10/12; macro recall 0.9286; complete 6/7; MRR@8 1.0000; post-context evidence 10/12.
- rerank: evidence 11/12; macro recall 0.9643; complete 6/7; MRR@8 1.0000; post-context evidence 11/12.

Vector-only covers all required evidence in this small fixed set. Reranking improves RRF evidence coverage on E02 but still misses its general-applications heading; complete-question count does not improve. This is retrieval evidence, not a reranked-answer experiment. No production setting was changed.

## First-result failures and scoring

- E01: completed; facts 5/7; strict fail. Evidence VII.2/3 reached the model. F1-F5 are stated with S1; offset/withholding discount qualification and the remedied-defect/reduction clock are omitted.
- E02: completed; facts 0/5; strict fail. RRF misses general-applications heading and two-month paragraph. The answer generalizes six months and falsely denies an onlyfy retention section despite pages 10/11 in context. No complete rubric fact is satisfied.
- E03: failed; facts 0/10; strict fail. Generation failed after 60.438s with generation_provider_unavailable. Correct order-row evidence was in context. No response usage; timeout-like transport event, remote root cause unproven.
- E04: dependent_blocked; facts 0/2; strict fail. Not submitted because E03 failed; no reference-resolution observation. Counts as 0 in fixed denominators.
- E05: dependent_blocked; facts 0/0; strict fail. Not submitted because the required conversation chain was unavailable; not evidence of successful rejection or of an executed scope violation.
- E06: failed; facts 0/2; strict fail. Planner call failed after 60.328s with generation_provider_unavailable; CSV lookup was not reached.
- E07: failed; facts 0/4; strict fail. Model returned both exact order IDs correctly. Frozen QuestionTools rejects the second ID adjacent to the sentence-final period before lookup. Zero-external-call reproduction confirms punctuation sensitivity.
- E08: completed; facts 0/0; strict pass. Correct exact lookup of synthetic order returned total=0 and exact_not_found; no substituted order or price.
- E09: completed; facts 1/1; strict pass. Incoterms 2020 supported by terms page 1 S1, and explicit CSV exact miss retained in gaps/unresolved. One raw uncited segment was removed by validation; final answer still satisfies the required partial behavior.
- E10: completed; facts 3/3; strict pass. All three numeric facts match Lunis page 4 and S1, with units and full luminous-flux range.
- E11: completed; facts 1/2; strict fail. The direct yes/no question is correctly answered: recessed is silver only. Strict preapproved F1 also requires enumerating white/black/silver; this is omitted. Do not mislabel this as wrong colour attribution.
- E12: failed; facts 0/4; strict fail. Correct two-order plan rejected at the sentence-final period before lookup. Same defect as E07; no price/date answer.

## Interpretation and limits

E07 and E12 expose a deterministic literal-boundary defect: the correct final order ID is rejected when followed by a sentence-ending period. An isolated real-CSV QuestionTools replay succeeds with a question mark, comma or no punctuation, with zero provider calls. This is a blocker candidate, not a supplier/model failure. Product repair and affected reruns require an explicit freeze exception and a new call budget; first results remain unchanged.

E01 omits required conditions despite correct evidence. E02 combines retrieval omissions with a false attribution/absence statement. E11 answers the direct silver-only question correctly but misses the rubric-required enumeration of all housing colours; report this as rubric completeness, not a wrong yes/no answer.

E03/E06 are timeout-like 60-second provider-unavailable events. The remote cause is unproven. E04/E05 were not executed, so this run provides no direct observation of multi-turn behavior. CSV positive lookups never executed successfully: fixed-denominator recall is 0/5, but this is not evidence that the exact CSV index returned wrong rows. Two of three fixed exact-miss cases pass; the third was dependent-blocked.

Citation-pair support is 16/17. This excludes uncited gaps from its denominator; E02 also contains an explicit false gap statement. Required-fact citation coverage is separately 10/40.

Observed backend turns: 10; median including failed turns 2.485s. Completed-turn median 2.485s. Two dependent-blocked turns have no latency. Query embeddings were warmed by the fixed retrieval comparison; these are not cold-start browser measurements. No stable P95 or model ranking is claimed.

Known successful token usage at protocol list prices: USD 0.018611; two failed generation calls have unknown usage/billing. Conservative reserved amount: USD 0.223632, within USD2. Neither amount is an invoice.

Development, document-holdout and same-file-holdout summaries are separate in summary.json/summary.csv and the HTML report. Two holdout PDF questions share one document; the CSV holdout shares a development file. No independence or unseen-domain claim. Judgments were source-reviewed by the assistant under the approved rubric, not independently double-rated by humans.

## Reproduction

Open report.html locally for filtering and per-turn details. JSONL preserves original requests, evidence, responses and attempts; review.json records the source-grounded judgments. Recompute every derived result without a key:

```sh
python eval/summarize_m50.py eval/results/m50/run-20260927-ab-01
```

For a new live run, follow eval/README.md using the recorded evaluation commit, original files with matching hashes, the pinned tokenizer and your own credentials. New output/runtime directories are mandatory. Provider models/defaults, quota and network behavior may vary. The raw results do not prove the separate M5 Docker/browser clean-install acceptance.
