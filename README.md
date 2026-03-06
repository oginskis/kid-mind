# kid-mind

An AI-powered European ETF research assistant grounded in official PRIIPs KID (Key Information Document) data. Ask anything about European ETFs — costs, risks, holdings, comparisons, live prices, or provider coverage. Currently covers **1,400+ funds** across 4 major providers: Vanguard, iShares, Xtrackers, and SPDR.

## What problem does this solve?

European investors face a fragmented landscape: over a thousand ETFs spread across multiple providers, each publishing standardised but hard-to-compare KID documents. Reading through hundreds of PDFs to find the cheapest S&P 500 tracker, compare risk levels, or understand what a fund actually invests in is impractical.

kid-mind automates the entire pipeline — from discovering and downloading those documents, to parsing and indexing them, to answering natural-language questions backed by the official data. Instead of manually opening PDFs, you ask questions like:

- *"What are the cheapest equity ETFs from iShares?"*
- *"Compare costs of S&P 500 trackers across all providers"*
- *"Which funds have risk level 2 or lower?"*
- *"What does the Xtrackers MSCI World ETF invest in?"*

Every answer is grounded in the actual KID documents — no hallucination, no guesswork.

## Architecture overview

```mermaid
flowchart TD
    subgraph Providers["ETF Provider Websites"]
        V[Vanguard] ~~~ I[iShares]
        X[Xtrackers] ~~~ S[SPDR]
    end

    subgraph Pipeline["Data Pipeline"]
        D1[Discover ISINs] --> D2[Download KID PDFs]
        D2 --> D3[Parse & chunk]
        D3 --> D4[Embed & index]
    end

    DB[(ChromaDB)]

    subgraph Tools["Agent Tools"]
        T1[Semantic search]
        T2[Filter by risk / provider / year]
        T3[ISIN lookup & compare]
        T4[Live price]
        T5[Chart rendering]
    end

    subgraph External["External APIs"]
        OF[OpenFIGI
ISIN → ticker]
        YF[yfinance
market prices]
    end

    LLM[LLM — Claude / Ollama / OpenAI]
    UI[Streamlit chat UI]

    Providers --> Pipeline
    D4 --> DB
    DB <--> Tools
    T4 --> OF --> YF
    Tools <--> LLM
    LLM <--> UI
```

## Components

### Data pipeline

Three phases turn provider websites into searchable vectors:

[**1. ISIN discovery**](.claude/skills/kid-collector/scripts/discover_isins.py) — scrapes each provider’s website to find all available ETF ISINs. Vanguard and iShares need browser automation (Playwright); Xtrackers and SPDR work with plain HTTP.

[**2. KID download**](.claude/skills/kid-collector/scripts/download_kids.py) — fetches the PDF documents via direct HTTP. Downloads are resumable — re-running skips files you already have.

[**3. Chunking and indexing**](src/kid_mind/parser.py) — converts PDFs into searchable knowledge. Each document is parsed into Markdown, split along the standardised EU KID headings (product description, risks, costs, etc.), then semantically sub-chunked so each piece stays on a single topic. Structured metadata (product name, risk level, launch year) is extracted and stored alongside each chunk.

The section-aware chunking means a cost question matches cost sections, not unrelated product descriptions. If a document doesn’t follow the standard headings, the system falls back to storing the full text as a single chunk.

### ChromaDB

[ChromaDB](https://www.trychroma.com/) is the vector store. It holds the embedded chunks with metadata, so the agent can combine semantic search (“find ETFs investing in emerging markets”) with exact filters (“only Vanguard, risk level 3”) in a single query.

Embedding models are pluggable — works with Ollama, OpenAI, or local sentence-transformers out of the box.

### Reranking

An optional second pass that improves search quality. After ChromaDB returns initial candidates based on embedding similarity, a cross-encoder model re-scores each result by reading the query and document together. This is more accurate than embedding comparison alone but too slow to run on the whole collection, so it only runs on the top candidates. Configurable in `.env`, falls back gracefully if disabled.

### Agent and tools

Two interchangeable backends:

- [**PydanticAI**](src/kid_mind/agent_pydantic.py) (default) — works with any OpenAI-compatible LLM (Ollama, OpenAI, LiteLLM). Recommended for local or self-hosted setups.
- [**Claude Agent SDK**](src/kid_mind/agent.py) — uses Anthropic’s Claude. Requires an API key.

The agent has access to these tools:

- [**Search**](src/kid_mind/tools.py) — semantic similarity search across all KID documents. Finds funds by topic, sector, region, or strategy — e.g. “technology sector ETFs” or “government bonds”
- [**Filter**](src/kid_mind/tools.py) — structured filtering by risk level (1–7), provider, launch year, or any combination. Returns exact, complete results — no fuzzy matching
- [**ISIN lookup**](src/kid_mind/tools.py) — retrieves the full KID document for a specific fund by ISIN, or compares multiple funds side by side in a single call
- [**Live price**](src/kid_mind/tools.py) — resolves an ISIN to a ticker via OpenFIGI, then fetches the current market price from yfinance. Best coverage on Xtrackers and SPDR
- [**Charts**](src/kid_mind/agent_pydantic.py) — the agent can render bar, horizontal bar, and pie charts inline in the Streamlit UI for visual comparisons like risk distribution or provider breakdown

Every answer is grounded in the retrieved documents — the agent doesn’t guess or fill gaps with general knowledge.

### Streamlit app

A [chat interface](streamlit_app.py) built with [Streamlit](https://streamlit.io/). Includes a welcome screen with example questions, conversational message history, inline Plotly charts when the agent visualises data, and a sidebar with provider logos. Custom-themed with a clean blue/grey palette.

### Observability

Optional [Arize Phoenix](https://phoenix.arize.com/) integration for tracing LLM calls, tool usage, and latencies via OpenTelemetry.

## Running it locally

### Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** — Python project and dependency manager
- **Docker** — for running ChromaDB

### Step 1: Clone and install dependencies

```bash
git clone https://github.com/oginskis/kid-mind.git
cd kid-mind
uv sync
```

### Step 2: Configure environment

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`. The agent works with multiple LLM providers — pick the setup that fits you:

**Inference (LLM):**

| Provider | Config | Notes |
|----------|--------|-------|
| **Ollama** (local) | `OPENAI_API_BASE=http://localhost:11434/v1` `OPENAI_API_KEY=ollama` `MODEL=qwen3:30b` | Free, needs decent GPU. Dummy API key required by SDK |
| **Gemini** | `GEMINI_API_KEY=AIza...` `MODEL=gemini-2.5-flash` | Native provider, no proxy needed |
| **OpenAI** | `OPENAI_API_BASE=https://api.openai.com/v1` `OPENAI_API_KEY=sk-...` `MODEL=gpt-4.1` | **Requires Tier 2+** ($50 paid). Tier 1 has a 30k TPM limit — a single agent request exceeds it |
| **Anthropic** | `AGENT_BACKEND=claude` `ANTHROPIC_API_KEY=sk-ant-...` | Switches to Claude Agent SDK backend |
| **Other** (LiteLLM, vLLM, etc.) | `OPENAI_API_BASE=<url>` `OPENAI_API_KEY=<key>` `MODEL=<model>` | Any OpenAI-compatible API works |

**Embeddings** can use a different provider than inference. Set `EMBEDDING_API_BASE` and `EMBEDDING_API_KEY` to point embeddings at a separate endpoint. If not set, they fall back to the inference endpoint. If no API key is set at all, local sentence-transformers (`all-MiniLM-L6-v2`) are used automatically.

```bash
# ── Inference: pick one ──
# Ollama (local)
OPENAI_API_BASE=http://localhost:11434/v1
OPENAI_API_KEY=ollama
MODEL=qwen3:30b

# Gemini (uncomment to use instead of OpenAI-compatible)
# GEMINI_API_KEY=AIza...
# MODEL=gemini-2.5-flash

# ── Embeddings ──
# Uses inference endpoint by default. Set these to use a different provider:
# EMBEDDING_API_BASE=https://other-endpoint.com/v1
# EMBEDDING_API_KEY=sk-...
EMBEDDING_MODEL=nomic-embed-text

# ── ChromaDB ──
CHROMADB_HOST=localhost
CHROMADB_PORT=8000

# ── Optional ──
RERANKER_ENABLED=true
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
ANTHROPIC_API_KEY=
AGENT_BACKEND=pydantic   # "pydantic" (default) or "claude"
```

### Step 3: Start ChromaDB

```bash
docker compose up -d
```

Verify it's running:

```bash
curl http://localhost:8000/api/v2/heartbeat
```

### Step 4: Discover ISINs and download KID documents (optional)

This step discovers ETF ISINs from provider websites and downloads KID PDFs. It takes a while — discovery involves scraping 4 provider sites, and downloading all ~1,400 PDFs can take an hour or more.

**You can skip this step.** The repo includes 10 sample KID PDFs per provider (40 total) in `data/kids/`, enough to build a working index and try the agent.

#### Option A: Use the agent skill

The [kid-collector skill](.claude/skills/kid-collector/) automates the entire process. If you're using Claude Code or GitHub Copilot with agent mode, just ask:

> *"Discover ISINs and download KID documents for all providers"*

The skill handles Playwright setup, discovery, downloading, and parallelisation automatically. See [`.claude/skills/kid-collector/SKILL.md`](.claude/skills/kid-collector/SKILL.md) for details.

#### Option B: Run the scripts manually

Install Playwright (one-time, only needed for Vanguard and iShares discovery):

```bash
uv run --with-requirements .claude/skills/kid-collector/scripts/requirements.txt \
  python -m playwright install chromium
```

Discover ISINs and download KIDs:

```bash
REQS=.claude/skills/kid-collector/scripts/requirements.txt
SCRIPTS=.claude/skills/kid-collector/scripts

# Discover all ISINs
uv run --with-requirements $REQS $SCRIPTS/discover_isins.py

# Download all KID PDFs
uv run --with-requirements $REQS $SCRIPTS/download_kids.py

# Or target a single provider with a limit
uv run --with-requirements $REQS $SCRIPTS/discover_isins.py -p vanguard
uv run --with-requirements $REQS $SCRIPTS/download_kids.py -p spdr -m 10
```

### Step 5: Build the ChromaDB index

Parse the KID PDFs, chunk them, and upsert into ChromaDB:

```bash
uv run python chunk_kids_cli.py
```

The 40 sample documents included in the repo take around 10–15 minutes to index. Indexing the full dataset of 1,400+ PDFs takes several hours — Docling PDF parsing is CPU-intensive.

### Step 6: Run the Streamlit app

```bash
uv run streamlit run streamlit_app.py
```

Opens at `http://localhost:8501`. Ask questions, compare ETFs, render charts.

## Keeping data up to date

Check for new or updated KID documents:

```bash
# Re-discover ISINs (new funds may have been added)
uv run --with-requirements .claude/skills/kid-collector/scripts/requirements.txt \
  .claude/skills/kid-collector/scripts/discover_isins.py

# Check for updated documents
uv run --with-requirements .claude/skills/kid-collector/scripts/requirements.txt \
  .claude/skills/kid-collector/scripts/update_kids.py

# Re-index changed documents
uv run python chunk_kids_cli.py
```

## Testing

```bash
uv run python -m pytest tests/ -v
```

The test suite covers three layers:

**[Chunking pipeline tests](tests/test_chunk_pipeline.py)** — verify that the PDF parsing and chunking pipeline produces correct output. Each of the 9 test PDFs (from all 4 providers) is processed and compared against committed [ground truth JSON](tests/fixtures/ground_truth/). Tests check chunk count, section names and ordering, metadata extraction (risk level, product name, launch year), text length stability (within 10% tolerance for minor Docling changes), and presence of EU-mandated key phrases in the right sections. The ground truth is auto-regenerated at test time from the same pipeline run, so tests stay self-consistent even when the semantic chunker produces slightly different splits.

**[Content correctness tests](tests/test_chunk_pipeline.py)** — structural invariants that must hold for any correctly parsed KID, independent of ground truth. These use regex patterns to verify that risk classification text lands in the risks section (not costs or product description), cost data appears in the costs section, performance scenarios are in risks, and every document produces the expected 4-section structure. These catch section mis-placement bugs that ground truth tests alone might miss.

**[Tool integration tests](tests/test_tools.py)** — 83 tests covering all tool functions against an in-memory ChromaDB seeded with the test fixture chunks. Validates semantic search relevance (e.g. a “gold” query finds gold ETCs), section and provider filtering, ISIN lookup, multi-ISIN comparison, provider listing, metadata filtering, and price lookup with mocked yfinance/OpenFIGI responses.

**[Section splitting unit tests](tests/test_section_splitting.py)** — fast tests using synthetic Markdown (no PDF processing). Cover the regex-based section splitter, SRI paragraph relocation, metadata extraction, and edge cases like missing headings or non-standard formats.

## Project structure

```
kid-mind/
├── streamlit_app.py               # Streamlit chat UI
├── agent_cli.py                   # CLI agent (Claude Agent SDK)
├── chunk_kids_cli.py              # Chunking pipeline CLI
├── src/kid_mind/                  # Core application package
│   ├── config.py                  # All configuration (env vars)
│   ├── prompt.py                  # Agent system prompt
│   ├── parser.py                  # PDF → markdown → sections → chunks
│   ├── tools.py                   # ChromaDB tools (search, filter, price)
│   ├── agent.py                   # Claude Agent SDK wrapper
│   └── agent_pydantic.py          # PydanticAI agent wrapper
├── assets/                        # UI assets (logos, CSS)
├── data/
│   ├── isins/                     # Discovered ISINs (JSON per provider)
│   ├── kids/                      # Downloaded KID PDFs
│   └── chunks/                    # Debug JSON output
├── tests/                         # Test suite (83+ tests)
├── docker-compose.yml             # ChromaDB service
├── pyproject.toml                 # Dependencies and project config
└── .claude/skills/kid-collector/  # ISIN discovery and KID download scripts
```

## License

This project is for research and educational purposes. KID documents are public regulatory disclosures published by fund providers under EU PRIIPs regulation.
