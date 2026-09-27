# Evaluation

The first formal run is [run-20260927-ab-01](results/m50/run-20260927-ab-01/report.md).
Open its [HTML report](results/m50/run-20260927-ab-01/report.html) locally for filtering
and per-case details. The [English protocol](results/m50/run-20260927-ab-01/protocol.md)
defines questions, evidence standards, denominators, configurations and budget.

## Recompute saved results

From the repository root, using Python 3.12:

```sh
python eval/summarize_m50.py eval/results/m50/run-20260927-ab-01
```

No API key or original document is needed. This recomputes metrics from saved
reviewed judgments; it does not independently regrade answers. Recomputing after
translation updates the protocol artifact hash in summary.json; scores are unchanged.

## Reproduce the original live run

Use a separate checkout of evaluation commit
`859447f9b42e999cc07c603c6a88634b5c1d9984`. The original runner requires product code
matching `7811243937e67e4e4d02854ffc616ad69736204d`; the current period fix deliberately
differs. Preserve the history when cloning. That checkout includes the original
protocol required by the runner.

1. Install Python 3.12 dependencies from `backend/requirements.lock.txt` and activate
   the environment. Optional budget tests also need `backend/requirements-dev.lock.txt`.
2. Obtain the five originals from [SITECO downloads](https://www.siteco.com/metanavigation/downloads).
   `eval/cases/m50_protocol.json` lists their paths and SHA256 values. Put them under
   `data/` at those paths; the runner rejects hash mismatches.
3. Prepare the tokenizer: `python scripts/prepare_voyage_tokenizer.py data/runtime/tokenizers`.
4. Save your own Gemini/Voyage keys in local files, then run:

```sh
python eval/run_m50.py --prepare --tokenizer data/runtime/tokenizers/voyage-4-tokenizer.json
python eval/run_m50.py --authorized-a-b --tokenizer data/runtime/tokenizers/voyage-4-tokenizer.json --output eval/results/m50/my-run --runtime tmp/m50-my-run/runtime --gemini-key /path/to/gemini-key.txt --voyage-key /path/to/voyage-key.txt
```

Live execution sends document text/evidence to providers and may incur charges.
Use fresh output/runtime directories. The A+B runner caps attempts at 153 and uses
a USD2 estimated-cost reserve; it does not run C/Groq. It ingests the complete
corpus and runs the fixed retrieval controls before end-to-end turns, warming query
embeddings. Provider outputs and timing can vary. New live results require fresh
source-grounded review and a report based on that run.

## Files and provenance

- `manifest.json`: original code/configuration, material and protocol hashes.
- `cases.json`, `review.json`, `scores.jsonl`: case definitions and reviewed scoring.
- `ingestion.jsonl`, `attempts.jsonl`, `generation.jsonl`, `retrieval.jsonl`,
  `answers.jsonl`: safe execution records. Count unique attempts, not log lines.
- `summary.json`, `summary.csv`, `report.md`, `report.html`: derived presentation.

The delivered `protocol.md` is an English translation. Its bytes differ from the
original `protocol_sha256`; the original is retained at
`c5421f2:eval/results/m50/run-20260927-ab-01/protocol.md`. The runtime original used LF except for its final two CRLF line endings; Git
normalizes these to LF. Restore those two endings to verify the original byte hash.
Questions, raw results, annotations and recorded hashes are unchanged.

The sentence-final-period defect was fixed after this run. Run
`python -m pytest backend/tests/test_questions.py -q` with development dependencies
to check current local behavior. The historical `reproduce_m50_boundary.py` script
belongs with the original evaluation checkout, not the fixed product.
