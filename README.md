# SITECO Document Chat

## 1. Demo

Upload documents, ask questions, and inspect the sources behind each answer.
The demo combines a React chat interface with a FastAPI retrieval backend.
The demo now supports pdf and csv files. 
All evaluation data comes from https://www.siteco.de/metanavigation/downloads

## 2. Repository structure

Repository layout:

```text
backend/          Backend application and tests
frontend/         Chat interface
scripts/          Setup utilities
tests/            Integration and browser tests
eval/             Evaluation runner, cases and results
compose.yaml      Docker startup
.env.example      Configuration template
README.md
```

## 3. Run the application

Run commands from the repository root. Copy `.env.example` to `.env` and configure:

- `GEMINI_API_KEY`: required for the default Gemini model.
- `VOYAGE_API_KEY`: required for PDF embedding and retrieval.
- `GROQ_API_KEY`: required only when choosing Groq.
- `GENERATION_PROVIDER`: `gemini` (default) or `groq`.
- `GEMINI_GENERATION_MODEL` / `GROQ_GENERATION_MODEL`: model selection.
- `DATA_DIR`: local runtime directory; default `data/runtime`.
- `HOST_DATA_DIR`: Docker runtime directory; default `./data/runtime`.
- `HOST_PORT` / `FRONTEND_PORT`: Docker ports; defaults `8000` / `8080`.

Additional settings and defaults are in `.env.example`. Keep API keys local.

### Local startup

Requires Python 3.12 and Node.js 24. PowerShell:

```powershell
py -3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
backend/.venv/Scripts/python.exe scripts/prepare_voyage_tokenizer.py data/runtime/tokenizers
backend/.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
npm ci --prefix frontend
npm run dev --prefix frontend
```

Open **http://127.0.0.1:5173**. If you change `DATA_DIR`, use its `tokenizers`
subdirectory in the preparation command.

### Docker startup

Requires Docker with Linux containers:

```sh
docker compose build
docker compose run --rm --no-deps backend python -m app.prepare_tokenizer /app/runtime/tokenizers
docker compose up -d --wait --wait-timeout 60
```

Open **http://127.0.0.1:8080**. Stop with `docker compose down`.

## 4. Implemented features

- PDF/CSV upload with processing status.
- Text-PDF hybrid retrieval and exact order lookup in SITECO price-list CSVs.
- Questions across selected documents and follow-up conversation memory.
- Source citations, original PDF page highlighting and CSV record previews.
- Gemini/Groq configuration, adjustable Top K and optional Voyage reranking.

## 5. Evaluation

First evaluation: 12 conversation turns and 7 PDF retrieval queries.

- Strict answer pass: **3/12**; required-fact coverage: **10/40**.
- Evidence recall: lexical **9/12**, vector **12/12**, RRF **10/12**, reranked **11/12**.

Results include provider failures and blocked turns. The later order-ID punctuation
fix is locally tested; these scores remain the original pre-fix results.

Open the [report](eval/results/m50/run-20260927-ab-01/report.html) locally, or read
its [Markdown version](eval/results/m50/run-20260927-ab-01/report.md).

Recompute saved scores without API calls:

```sh
python eval/summarize_m50.py eval/results/m50/run-20260927-ab-01
```

For a live evaluation, use the recorded evaluation commit, matching source
materials and your own Gemini/Voyage keys. Commands and configuration:
[Evaluation README](eval/README.md).

## 6. Technical choices and rationale

To be completed after discussion.

## 7. Diagnosed issues and next improvements

- Some prose-PDF evidence is lost during final ranking: improve section coverage.
- Answers can omit conditions or misattribute evidence: improve answer completeness
  and grounding.
- Provider failures can block follow-up turns: improve diagnostics and recovery.
- Sentence-final periods previously blocked valid order IDs: fixed; live regression
  is pending.
