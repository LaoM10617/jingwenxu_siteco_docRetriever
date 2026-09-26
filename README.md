# SITECO Document Retriever

M0 development foundation is complete. The repository currently contains three standalone migrated modules (rank fusion, lexical retrieval, and tracing) and 10 tracing tests. Application upload, question answering, and Docker application startup are not implemented yet.

See [development setup](docs/development.md) for Python 3.12 environment creation, pinned dependency installation, and verification commands. See [reuse notes](docs/reuse.md) for provenance and migration boundaries.

## Planned directory structure

Empty directories are not tracked by Git. Requirements, private materials, runtime data, and temporary files below are local-only.

```text
Retrieval_SITECO/
├── README.md                      # Entry point for operators and reviewers
├── AGENTS.md                      # Project collaboration rules
├── requirements_draft.md           # Requirements, scope of support, and items for discussion
├── milestones_and_execution_plan.md
├── decisions.md                    # Confirmed choices and testing boundaries
├── .gitignore
├── .dockerignore
├── .env.example                    # Configuration example (no real keys included)
│
├── backend/                        # Backend source code, dependencies, and unit tests
│   ├── app/
│   └── tests/
│
├── frontend/                       # Frontend source code, dependencies, and unit tests
│   └── src/
│
├── tests/                          # Migrated tracing test and future cross-stack checks
│   ├── e2e/
│   └── fixtures/                   # Small, controlled test samples suitable for version control
│
├── eval/                           # Acceptance material definitions and performance checks
│   ├── materials.md                # Document sources, characteristics, and acquisition methods
│   ├── cases/                      # Questions, key answer points, and evidence locations
│   └── results/                    # Filtered acceptance records
│
├── docs/                           # Supplementary documentation
│   ├── development.md              # Development environment setup and check commands
│   └── reuse.md                    # Migration sources, modifications, dependencies, and verification
│
├── logs/                           # Manually maintained implementation records
│   ├── current.md                  # Standard handover entry point
│   └── m0.md                      # Phase-specific records (as needed)
│
├── scripts/                        # Development and verification scripts
├── data/                           # Local runtime data (uploaded files, indices, etc.)
├── private/                        # Non-standard deliverables (exam questions, emails, etc.)
└── tmp/                            # Rendered output, debug logs, and temporary files
```
