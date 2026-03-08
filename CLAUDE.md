# kid-mind

AI-powered European ETF research assistant, grounded in official PRIIPs KID (Key Information Document) data. Ask anything about European ETFs — costs, risks, holdings, comparisons, live prices, or provider coverage. 1,400+ funds across 4 providers: Vanguard, iShares, Xtrackers, SPDR.

## Mandatory rules

- **Read and follow all coding standards in `AGENTS.md`** before writing any code.
- **After any codebase changes, update `CLAUDE.md` and `AGENTS.md`** to keep them in sync with the codebase. This includes: new files, renamed modules, changed project structure, new dependencies, new scripts, changed conventions, or removed features. This is mandatory — stale docs cause compounding errors.

## Project overview

A **KID** (Key Information Document) is a standardised EU-mandated disclosure document required under the PRIIPs regulation. Every European investment product must publish one, covering objectives, risks, costs, and performance scenarios in a consistent format.

kid-mind discovers, downloads, and analyses these KID PDFs from major European ETF providers: Vanguard, iShares, Xtrackers, and SPDR. It chunks them into a vector store so an AI agent can answer questions grounded in the official documents.

## Tech stack

- **Python 3.10+**
- **uv** — project and dependency management
- **Playwright** — browser automation for ISIN discovery (JS-rendered provider sites)
- **requests** — direct HTTP for all KID downloads
- **lxml** — XML parsing (Euronext feed)
- **Docling** — PDF to markdown conversion (KID chunking)
- **Chonkie** — semantic text chunking
- **ChromaDB** — vector store for chunked KID documents
- **sentence-transformers** — `all-MiniLM-L6-v2` embeddings (local fallback)
- **google-genai** — native Gemini embedding API (`gemini-embedding-001`)
- **yfinance** — ETF price lookups (lazy-loaded)
- **Pydantic AI** — agent framework (`agent_pydantic.py`)
- **Claude Agent SDK** — agent framework (`agent.py`)
- **Ruff** — linting and formatting (dev dependency)

## Setup

```bash
# Install application dependencies
uv sync

# One-time: install Chromium for Playwright (ISIN discovery only)
uv run --with-requirements .claude/skills/kid-collector/scripts/requirements.txt \
  python -m playwright install chromium
```

## Project structure

```
kid-mind/
├── pyproject.toml                 # uv project config, ruff config, application deps
├── uv.lock                       # Locked dependency versions
├── CLAUDE.md                      # Project overview, structure, how to run (this file)
├── AGENTS.md                      # Coding standards — read before writing code
├── Dockerfile                     # App image (Streamlit + chunker)
├── .dockerignore                  # Exclude data/, .env, .git, etc.
├── chunk_kids_cli.py              # CLI: batch chunking, ChromaDB upsert, JSON dump
├── agent_cli.py                   # CLI: interactive / one-shot agent queries
├── streamlit_app.py               # Streamlit chat UI (PydanticAI or Claude SDK backend)
├── src/kid_mind/                  # Application package (src layout)
│   ├── __init__.py
│   ├── config.py                  # Centralised env-based configuration
│   ├── prompt.py                  # System prompt for the ETF research assistant
│   ├── parser.py                  # KID PDF processing (Docling → sections → chunks)
│   ├── tools.py                   # ChromaDB tool functions (search, filter, price)
│   ├── agent.py                   # Claude Agent SDK wrapper (@tool decorators)
│   └── agent_pydantic.py          # Pydantic AI agent (OpenAI-compatible LLM)
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Shared fixtures (pipeline_results, chromadb_collection)
│   ├── generate_ground_truth.py   # Ground truth JSON generator
│   ├── test_tools.py              # Tool function tests (83 tests)
│   ├── test_chunk_pipeline.py     # Chunking pipeline tests
│   └── test_section_splitting.py  # Section splitting tests
├── k8s/                           # Kubernetes manifests
│   ├── namespace.yaml
│   ├── chromadb/
│   │   ├── configmap.yaml
│   │   ├── statefulset.yaml
│   │   └── service.yaml
│   ├── streamlit/
│   │   ├── configmap.yaml
│   │   ├── secret.yaml            # CHANGEME: set GEMINI_API_KEY before applying
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── gateway.yaml           # Gateway API: HTTPS ingress + HTTPRoute + HealthCheckPolicy
│   └── chunker/
│       ├── configmap.yaml         # ChromaDB + embedding config for the job
│       ├── secret.yaml            # CHANGEME: set GEMINI_API_KEY before applying
│       └── job.yaml               # K8s Job: init container (GCS→PDFs) + chunker
├── scripts/
│   ├── upload-kids-to-gcs.sh      # Upload KID PDFs from remote box to GCS
│   └── setup-workload-identity.sh # Provision Workload Identity for chunker job
├── .claude/skills/kid-collector/
│   ├── SKILL.md                   # Skill instructions
│   ├── scripts/
│   │   ├── config.py              # Shared constants, URLs, retry/rate-limit settings
│   │   ├── discover_isins.py      # ISIN discovery via Playwright + HTTP scraping
│   │   ├── download_kids.py       # KID PDF download (all direct HTTP)
│   │   ├── update_kids.py         # Detect new/updated KIDs via metadata + hash
│   │   └── requirements.txt       # Skill-only deps (playwright, requests, lxml)
│   └── references/                # Provider-specific technical docs
├── .claude/skills/ssh/
│   ├── SKILL.md                   # Skill instructions
│   └── scripts/
│       ├── ssh-run.sh             # Sync + execute command on remote host
│       └── sync.sh                # Rsync scripts to remote host
├── .claude/skills/cloud-build/
│   └── SKILL.md                   # Build & push Docker images via Cloud Build
├── .claude/skills/deploy/
│   └── SKILL.md                   # Deploy arbitrary docker-compose files via SSH
├── data/isins/                    # ISINs + download metadata (JSON per provider)
├── data/kids/                     # Downloaded KID PDFs (subdir per provider)
└── data/chunks/                   # Debug JSON output from chunking pipeline
```

## Running scripts

Run from the project root. All commands use `uv run`.

```bash
REQS=.claude/skills/kid-collector/scripts/requirements.txt
SCRIPTS=.claude/skills/kid-collector/scripts

# ── Skill scripts (use --with-requirements for isolated skill deps) ──

# Discover ISINs — all providers
uv run --with-requirements $REQS $SCRIPTS/discover_isins.py

# Discover ISINs — single provider
uv run --with-requirements $REQS $SCRIPTS/discover_isins.py -p vanguard

# Download KIDs — all providers
uv run --with-requirements $REQS $SCRIPTS/download_kids.py

# Download KIDs — single provider, limit 10
uv run --with-requirements $REQS $SCRIPTS/download_kids.py -p spdr -m 10

# Show browser UI for debugging
uv run --with-requirements $REQS $SCRIPTS/discover_isins.py -p ishares --no-headless

# Check for new/updated KIDs — all providers
uv run --with-requirements $REQS $SCRIPTS/update_kids.py

# Check single provider, limit 5
uv run --with-requirements $REQS $SCRIPTS/update_kids.py -p vanguard -m 5

# Add metadata to ISIN entries from existing PDFs
uv run --with-requirements $REQS $SCRIPTS/update_kids.py --backfill

# Force re-check all documents
uv run --with-requirements $REQS $SCRIPTS/update_kids.py --force

# ── Chunking pipeline (CLI runner at project root) ──

# Chunk KIDs and store in ChromaDB — all providers
uv run python chunk_kids_cli.py

# Single provider, limit 10
uv run python chunk_kids_cli.py -p vanguard -m 10

# JSON debug output only, no ChromaDB needed
uv run python chunk_kids_cli.py --skip-chromadb --dump-json

# JSON + ChromaDB
uv run python chunk_kids_cli.py --dump-json

# ── Infrastructure scripts ──

# Upload KID PDFs from remote box to GCS
./scripts/upload-kids-to-gcs.sh

# Dry run (show what would be uploaded)
./scripts/upload-kids-to-gcs.sh --dry-run

# Provision Workload Identity for chunker K8s Job
./scripts/setup-workload-identity.sh

# ── Tests ──

# Run all tests
uv run python -m pytest tests/ -v

# Run tool tests only
uv run python -m pytest tests/test_tools.py -v

# Run a specific test class
uv run python -m pytest tests/test_tools.py::TestGetEtfPrice -v
```

## Kubernetes deployment

The app runs on GKE Autopilot with ChromaDB (StatefulSet), Streamlit (Deployment), and a chunking Job.

**Important:** On GKE Autopilot, resource `limits` MUST equal `requests`.

```bash
# Deploy core infrastructure
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/chromadb/
# Edit k8s/streamlit/secret.yaml with your GEMINI_API_KEY first
kubectl apply -f k8s/streamlit/

# Deploy Gateway API (HTTPS ingress via kid.alteronic.dev)
kubectl apply -f k8s/streamlit/gateway.yaml

# Port-forward for local access
kubectl port-forward svc/chromadb -n kid-mind 8000:8000
kubectl port-forward svc/streamlit -n kid-mind 8501:8501
```

**HTTPS access:** `https://kid.alteronic.dev` via GKE Gateway API (`gke-l7-global-external-managed`) with certificate map `alteronic-certificate-map`. DNS managed in Cloud DNS zone `alteronic-dev`.

### Chunking Job

The chunking job runs as a K8s Job with an init container that downloads KID PDFs from GCS, then the main container runs `chunk_kids_cli.py` against in-cluster ChromaDB.

```bash
# One-time: provision Workload Identity for GCS access
./scripts/setup-workload-identity.sh

# Upload KID data from remote box to GCS (source of truth)
./scripts/upload-kids-to-gcs.sh
# Dry run: ./scripts/upload-kids-to-gcs.sh --dry-run

# Run the chunking job (delete old job first if re-running)
kubectl delete job chunk-kids -n kid-mind --ignore-not-found
kubectl apply -f k8s/chunker/
kubectl logs -f job/chunk-kids -n kid-mind -c chunker
```

**GCS bucket:** `gs://kid-mind-data` — contains `kids/` (PDFs by provider) and `isins/` (JSON metadata).

**Workload Identity:** K8s SA `chunker` → GCP SA `kid-mind-chunker@alteronic-ai.iam.gserviceaccount.com` → `storage.objectViewer` on the bucket.

### Building the Docker image

Use the `cloud-build` skill or run directly:
```bash
gcloud builds submit \
  --tag europe-north1-docker.pkg.dev/alteronic-ai/kid-mind/kid-mind:latest \
  --project=alteronic-ai .
```

### Embedding model consistency

The embedding model used during chunking (indexing) MUST match the model used by Streamlit (query time). Set `EMBEDDING_MODEL` to the same value in both configmaps. Switching models requires re-indexing the entire collection.

## Embedding fallback chain

1. `EMBEDDING_API_KEY` set → OpenAI-compatible endpoint (Ollama, OpenAI, etc.)
2. `GEMINI_API_KEY` set (no `EMBEDDING_API_KEY`) → native Google GenAI API (`gemini-embedding-001`)
3. Neither → local sentence-transformers (`all-MiniLM-L6-v2`)

## Development conventions

- **Read `AGENTS.md` first** — it defines all coding standards (style, imports, error handling, logging, types, shell scripts).
- **Application code** lives in `src/kid_mind/` (standard src layout).
- **Skill scripts** (ISIN discovery, KID downloading) live in `.claude/skills/kid-collector/scripts/`.
- **Infrastructure scripts** (GCS upload, Workload Identity) live in `scripts/`.
- Application deps managed by uv via `pyproject.toml`. CLI runners live at project root.
- Provider-specific logic goes in dedicated functions, not separate files — keep the module count low.
- All HTTP requests must include rate-limiting delays and retry logic (see skill's `scripts/config.py`).
- Downloaded PDFs must be validated: `%PDF-` magic header + minimum 5 KB file size.
- Downloads are resumable — existing valid PDFs are skipped automatically.

## Deployment guardrails

- **NEVER rsync `.env` from local to remote.** Local and remote `.env` files have different model/API configurations. Always exclude `.env` when syncing code to the box. To change remote config, edit it directly via SSH.
- **NEVER overwrite remote `data/` directories.** They contain KID PDFs, ISIN metadata, and ChromaDB data that may differ from local.
- **Always edit code locally first, then sync** — never edit files directly on the remote box.
- **Rsync command must always include:** `--exclude='.env' --exclude='data/' --exclude='.venv' --exclude='__pycache__' --exclude='.git'`

## Provider technical notes

| Provider | KID download | ISIN discovery | Notes |
|----------|-------------|----------------|-------|
| Vanguard | Direct HTTP | Playwright (GraphQL) | `fund-docs.vanguard.com/{isin_lower}_priipskid_en.pdf` (~81%) |
| SPDR | Direct HTTP | Pure HTTP (sitemap) | Requires ISIN + ticker in URL (~94%) |
| iShares | Direct HTTP | Playwright (DOM scrape) | BlackRock document search API → PDF (~99%) |
| Xtrackers | Direct HTTP | Pure HTTP (sitemap.xml) | Two-step GUID resolution via `download.dws.com` (~98%) |

## Adding new features

When adding new capabilities:
- **Application modules** (chunking, analysis, API): add to `src/kid_mind/`, deps via `uv add <package>`
- **Skill scripts** (ISIN discovery, KID downloading): `.claude/skills/kid-collector/scripts/`, deps in skill's `requirements.txt`
- Keep `config.py` as the single source of truth for env vars and settings
- Data outputs go under `data/`, downloaded documents under `data/kids/`
- Follow coding standards in `AGENTS.md`
- **Update this file and `AGENTS.md`** to reflect the changes
