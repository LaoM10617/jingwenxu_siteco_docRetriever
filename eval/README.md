# Reproducing the M5.0 evaluation

The frozen product is `7811243937e67e4e4d02854ffc616ad69736204d`. The runner verifies that `backend/app` and the backend dependency lock have no differences from that commit. The evaluation code, protocol and case-set hashes are recorded in each run's `manifest.json`.

## Inspect or recompute existing results without API calls

Each result directory contains `cases.json`, `protocol.md`, `manifest.json`, `ingestion.jsonl`, `attempts.jsonl`, `generation.jsonl`, `retrieval.jsonl` and `answers.jsonl`. The JSONL files preserve requests/evidence/responses and failures; `attempts.jsonl` contains started and terminal events for the same attempt, so count terminal events or unique `(kind, attempt)`, not lines. Credentials and authorization headers are excluded.

The reviewed `scores.jsonl` will contain per-fact and per-evidence judgments with reasons. `summary.json`, `summary.csv`, `report.md` and the local visual report are derived outputs. Inspect scores against the original documents: rerunning arithmetic is not independent verification of the annotations. First result: [run-20260927-ab-01/report.md](results/m50/run-20260927-ab-01/report.md), with [interactive offline report](results/m50/run-20260927-ab-01/report.html) and [summary CSV](results/m50/run-20260927-ab-01/summary.csv). Live runner/protocol commit: `859447f9b42e999cc07c603c6a88634b5c1d9984`; product unchanged from `7811243`. The scoring/report code is in the subsequent results commit.

Recompute the published summaries, without any key or original PDF:

```sh
python eval/summarize_m50.py eval/results/m50/run-20260927-ab-01
```

This command reuses reviewed judgments; it does not independently re-grade language. For another live run, prepare a new `review.json` by checking each answer and evidence unit against the frozen rubric, then compute summaries. The current narrative report template documents this first run's findings; adapting a future run's narrative must not copy these findings without verification. Raw live execution is automated; semantic review remains an explicit review step.

Reproduce the sentence-final-period defect at commit `859447f9b42e999cc07c603c6a88634b5c1d9984` with the original CSV and a new runtime (no keys/network). Current code includes the P-041 fix, so the historical reproduction script must be run in a checkout of that original commit. To verify the fix on current code, run `python -m pytest backend/tests/test_questions.py -q`:

```sh
python eval/reproduce_m50_boundary.py --runtime tmp/m50-boundary-check/runtime
```

## Run A+B with your own credentials

This is an opt-in live run and may incur provider charges. C/Groq is not part of this runner. Do not replay automatically as part of CI.

1. Check out the evaluation commit recorded by the run and install the locked Python dependencies following the project README. Python 3.12 is the recorded runtime. Run from the repository root.
2. Obtain the five original SITECO files listed in `eval/cases/m50_protocol.json` from the SITECO download directory described in `eval/materials.md`, and place them at their listed paths under `data/`. Originals are not distributed in Git. Hash mismatches stop the run: if a newer download differs, it is a new dataset, not a reproduction of the recorded score.
3. Prepare the pinned Voyage tokenizer as described in the project README. The runner verifies its SHA256. A tokenizer file may be reused; document indexes, embeddings, answers and runtime databases may not.
4. Supply your own Gemini and Voyage credentials in local files, or pass their paths through `--gemini-key` and `--voyage-key`. Default local filenames are `Gemini_API_KEY.txt` and `voyage.txt`; both are Git-ignored. Do not commit them. Model access, sufficient account quota and network access are required.
5. Perform the offline preflight, then run only after accepting the protocol's material disclosure, request and USD2 reserve limits. Use new output/runtime directories every time.

Commands below use `python` from the activated backend environment and a tokenizer path you prepared:

```sh
python -m pytest eval/test_m50_budget.py -q
python eval/run_m50.py --prepare --tokenizer /path/to/voyage-4-tokenizer.json
python eval/run_m50.py --authorized-a-b --tokenizer /path/to/voyage-4-tokenizer.json --output eval/results/m50/my-run --runtime tmp/m50-my-run/runtime --gemini-key /path/to/gemini-key.txt --voyage-key /path/to/voyage-key.txt
```

The runner owns its standalone runtime and calls the frozen DocumentService, retrieval, AnswerService and QuestionTasks interfaces. This reproduces the backend evaluation chain, not browser/HTTP latency or the separate M5 Docker clean-install acceptance. No existing demo service or database is used. Material ingestion is always fresh; all five documents are ready before querying. The seven fixed retrieval queries warm the query cache before the twelve end-to-end turns; cache observations are recorded.

A has at most 32 generation attempts, 72 document-embedding attempts and 42 query-embedding attempts. B has at most 7 reranker attempts. These include failures and the frozen embedding gateway's bounded retries. There are no manual retries, provider switches, extra probes or C calls. The runner enforces input limits and a conservative USD2 reserve before provider operations; public prices in the protocol are not a verified bill. Generation usage is recorded when the API returns it.

If a run stops, preserve its directory. Do not reuse it or silently resume/retry. Read the failure record and obtain a separate budget decision for a new run. Once a holdout result informs changes, disclose that contamination; do not call it an unseen test again.

Reproduction means the same protocol, materials, code, configuration and scoring rules. Provider defaults, model alias changes, stochastic responses, quotas and network latency can change output and timing. Exact bitwise answers or matching latency are not promised.
