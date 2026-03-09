"""Centralised configuration loaded from environment variables.

All env-based settings live here. Other modules import from this file
instead of reading os.environ directly.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (walk up from this file: src/kid_mind/config.py → project root)
_project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_project_root / ".env", override=True)


def _env(key: str, default: str = "") -> str | None:
    """Read an env var, strip whitespace, return None if blank."""
    val = os.environ.get(key, default).strip()
    return val or None


# ── ChromaDB ─────────────────────────────────────────────────────────────────
CHROMADB_HOST = os.environ.get("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.environ.get("CHROMADB_PORT", "8000"))
CHROMADB_COLLECTION = os.environ.get("CHROMADB_COLLECTION", "kid_chunks")

# ── Inference (LLM) ─────────────────────────────────────────────────────────
# Priority: VERTEX_AI=true → Vertex AI regional endpoint (ADC auth).
#           GEMINI_API_KEY set → native Gemini provider (AI Studio).
#           Otherwise → OpenAI-compatible (OPENAI_API_BASE / OPENAI_API_KEY).
OPENAI_API_BASE = _env("OPENAI_API_BASE")
OPENAI_API_KEY = _env("OPENAI_API_KEY")
GEMINI_API_KEY = _env("GEMINI_API_KEY")

# ── Vertex AI ────────────────────────────────────────────────────────────────
# Set VERTEX_AI=true to use Vertex AI regional endpoints with ADC.
# Requires GOOGLE_CLOUD_LOCATION. GOOGLE_CLOUD_PROJECT is auto-detected on
# GKE; set it explicitly for local development.
# Auth: Workload Identity (GKE) or `gcloud auth application-default login` (local).
VERTEX_AI = os.environ.get("VERTEX_AI", "").strip().lower() == "true"
GCP_LOCATION = _env("GOOGLE_CLOUD_LOCATION")
GCP_PROJECT = _env("GOOGLE_CLOUD_PROJECT")

# ── Embeddings ───────────────────────────────────────────────────────────────
# Embeddings can use a DIFFERENT provider than inference.
#
# Provider selection (first match wins):
#   1. EMBEDDING_API_KEY set → OpenAI-compatible endpoint (Ollama, OpenAI, etc.)
#   2. VERTEX_AI=true → Vertex AI via google-genai SDK (ADC auth)
#   3. GEMINI_API_KEY set → native Google GenAI API (AI Studio)
#   4. None of the above → local sentence-transformers (all-MiniLM-L6-v2)
#
# IMPORTANT: the embedding model used at query time MUST match the one used
# when the ChromaDB collection was indexed. Switching models requires
# re-indexing (uv run python chunk_kids_cli.py).
EMBEDDING_API_BASE = _env("EMBEDDING_API_BASE") or OPENAI_API_BASE
EMBEDDING_API_KEY = _env("EMBEDDING_API_KEY") or OPENAI_API_KEY
EMBEDDING_MODEL = _env("EMBEDDING_MODEL")
EMBEDDING_DIMENSION = int(os.environ.get("EMBEDDING_DIMENSION", "768"))


# ── Search ───────────────────────────────────────────────────────────────────
SEARCH_RESULTS = 40  # results returned to the agent (fixed)
SEARCH_FETCH_NO_RERANK = 40  # candidates fetched when reranker is off
SEARCH_FETCH_RERANK = 60  # candidates fetched when reranker is on

# ── Reranker ─────────────────────────────────────────────────────────────────
# Set RERANKER_ENABLED=false to disable cross-encoder reranking.
RERANKER_ENABLED = os.environ.get("RERANKER_ENABLED", "true").strip().lower() != "false"
RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# ── Price lookup ──────────────────────────────────────────────────────────────
# OpenFIGI maps ISINs to tickers. We try European exchanges in priority order
# and use the first match to build a yfinance ticker (e.g. "IWDA" + ".AS").
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

# (OpenFIGI exchCode, yfinance suffix) — tried in order, first match wins
EXCHANGE_PRIORITY = [
    ("GY", ".DE"),  # Xetra (Germany)
    ("GR", ".DE"),  # Xetra (alternative code)
    ("LN", ".L"),  # London Stock Exchange
    ("NA", ".AS"),  # Euronext Amsterdam
    ("IM", ".MI"),  # Borsa Italiana (Milan)
    ("SW", ".SW"),  # SIX Swiss Exchange
]

# ── Phoenix / Arize telemetry ─────────────────────────────────────────────────
PHOENIX_COLLECTOR_ENDPOINT = _env("PHOENIX_COLLECTOR_ENDPOINT")
PHOENIX_API_KEY = _env("PHOENIX_API_KEY")
PHOENIX_PROJECT = _env("PHOENIX_PROJECT", "default")

# ── LLM model ───────────────────────────────────────────────────────────────
MODEL = _env("MODEL") or _env("OPENAI_MODEL")

# ── Streamlit UI ──────────────────────────────────────────────────────────────
AGENT_BACKEND = _env("AGENT_BACKEND") or "pydantic"  # "pydantic" or "claude"

# ── Static constants (not env-driven) ────────────────────────────────────────
SECTION_ORDER = {
    "product_and_description": 0,
    "risks_and_return": 1,
    "costs": 2,
    "tail": 3,
}
