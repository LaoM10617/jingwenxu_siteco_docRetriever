# Delivery and reviewer guide

## Handover and entry points

The handover is the GitHub repository with full source and intact commit history:
https://github.com/LaoM10617/jingwenxu_siteco_docRetriever

The repository is private. Reviewer access must be arranged before handing over
this link; local administrator access does not prove reviewer access. Keep the
existing history. A source ZIP is only an optional convenience and does not replace
the Git repository. No hosted application, public repository, Docker Hub image,
or exported runtime database is required by the case brief.

Clone the repository, record the delivered commit (`git rev-parse HEAD`), and follow
[the README Docker commands](../README.md#ask-questions-with-docker). Docker Desktop
must use Linux containers. Compose builds two images from source: a React static
frontend served by nginx and a single-process FastAPI backend. The frontend is
http://127.0.0.1:8080 by default; the backend is http://127.0.0.1:8000.
Changing FRONTEND_PORT/HOST_PORT changes these host URLs. The UI is the demonstration
entry point; `/api/health` only checks service health.

For the default live PDF path, supply your own GEMINI_API_KEY and VOYAGE_API_KEY.
GROQ_API_KEY is only required when explicitly choosing Groq. See `.env.example`
for model names, local rate limits, HOST_DATA_DIR and ports. Keys belong in local
runtime configuration or Settings, never in Git, Docker build arguments or the
frontend. Settings overrides are in memory and restart restores startup defaults.
Build/package downloads require internet; PDF embedding and model answers also
need provider connectivity, compatible accounts and quota. No developer keys or
account quota are included with delivery.

## Materials and reproducibility

Use text-layer PDFs (up to 50 pages) and the supported SITECO price-list CSV schema;
arbitrary spreadsheets, OCR and visual interpretation are outside the baseline.
Obtain example materials from https://www.siteco.com/metanavigation/downloads.
The [evaluation manifest](../eval/cases/m50_protocol.json) records exact filenames
and hashes. Original documents and the confidential case brief are not distributed
in this repository. Changed download hashes mean a different dataset.

The first formal [evaluation report](../eval/results/m50/run-20260927-ab-01/report.md)
and [offline HTML](../eval/results/m50/run-20260927-ab-01/report.html) preserve failures,
scores and limitations. Download/open the HTML locally; GitHub's file viewer is
not a hosted interactive report. Follow [eval/README.md](../eval/README.md) to
recompute existing summaries or reproduce the old live run at its recorded commit.
The period fix has [separate local verification](../eval/results/m50/period-validation-fix.md).
Do not describe those old scores as a post-fix live result.

## Decisions worth discussing

- React/TypeScript and FastAPI keep UI state and typed backend contracts explicit;
  the frontend and orchestration are implemented here, with provenance documented
  in [reuse notes](reuse.md).
- SQLite and embedded FAISS keep local startup small. No managed database or remote
  vector service is needed; the trade-off is a single-user, single-process demo.
- PDF text evidence uses lexical plus vector retrieval; CSV prices use exact,
  case-sensitive order lookup so a similar product cannot silently replace a miss.
- Temporary history resolves subjects; current selected documents supply fresh
  evidence. Citation identity checks do not prove generated semantic correctness.
- Reranking is optional and off by default. The small benchmark does not justify
  claiming universal gains or hiding provider failures behind automatic fallback.

## Ten-minute local demo

1. Show the running Docker services and open the frontend. Explain the tested
   configuration, local data directory and provider credentials without displaying keys.
2. Upload a text PDF, observe processing/ready, select it and ask a factual question.
   Expand a citation and inspect the original page and highlighted evidence.
3. Show a product question and follow-up in one conversation; change the selected
   scope and explain how missing evidence is reported rather than invented.
4. Upload the full supported CSV, ask for an exact order with a sentence-final
   period, inspect the source record, and demonstrate an exact miss.
5. Show the recorded evaluation and one genuine limitation. Explain failures and
   what you would change next; do not imply every benchmark question passes.

Reserve the remaining 20 minutes for architecture, trade-offs, failures and next
steps. For acceptance, start from an empty runtime and upload fresh materials;
a rehearsed populated workspace is not evidence of clean-install reproducibility.

## Current limitations and next work

The first benchmark exposed omitted qualifications, wrong attribution, two provider
failures and blocked follow-ups. Local regression fixes the deterministic period
bug but does not establish live answer quality. Priorities are prose-PDF evidence
coverage, faithful conditions/ownership, provider failure diagnosis and a fresh
regression set. There is no authentication, production hardening, OCR, durable
job queue or general semantic answer verifier. See the README for supported limits.

## Release gate

Current work is a delivery candidate, not final acceptance. Before handover:
verify the exact commit from a clean Docker runtime, complete browser/source checks,
perform the required final review, push the approved delivery version and confirm
reviewer access. Keep original evaluation results and full history. Exclude private
materials, credentials, development environments, runtime databases and caches from
any optional archive; generate it from the committed tree, not the project folder.
