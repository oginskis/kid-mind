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
load_dotenv(_project_root / ".env")


def _env(key: str, default: str = "") -> str | None:
    """Read an env var, strip whitespace, return None if blank."""
    val = os.environ.get(key, default).strip()
    return val or None


# ── ChromaDB ─────────────────────────────────────────────────────────────────
CHROMADB_HOST = os.environ.get("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.environ.get("CHROMADB_PORT", "8000"))
CHROMADB_COLLECTION = os.environ.get("CHROMADB_COLLECTION", "kid_chunks")

# ── Embeddings ───────────────────────────────────────────────────────────────
# Two modes, selected by whether OPENAI_API_KEY is set:
#
#   OPENAI_API_KEY set → remote OpenAI-compatible API (default: text-embedding-3-small)
#     Pros:  higher quality embeddings, no local GPU/CPU load
#     Cons:  requires network + API key, adds latency per call, costs money
#
#   OPENAI_API_KEY unset → local sentence-transformers (default: all-MiniLM-L6-v2)
#     Pros:  fully offline, free, no API dependency
#     Cons:  lower embedding quality (384-dim vs 1536-dim), slower on CPU,
#            downloads ~90 MB model on first run
#
# IMPORTANT: the embedding model used at query time MUST match the one used
# when the ChromaDB collection was indexed. Switching models requires
# re-indexing (uv run python chunk_kids_cli.py).
#
# Override the default model name with EMBEDDING_MODEL env var.
LOCAL_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_MODEL = _env("EMBEDDING_MODEL")
OPENAI_API_BASE = _env("OPENAI_API_BASE")
OPENAI_API_KEY = _env("OPENAI_API_KEY")
EMBEDDING_DIMENSION = int(os.environ.get("EMBEDDING_DIMENSION", "768"))

# ── Search ───────────────────────────────────────────────────────────────────
MAX_SEARCH_RESULTS = 20
DEFAULT_SEARCH_RESULTS = 10

# ── Reranker ─────────────────────────────────────────────────────────────────
# Set RERANKER_ENABLED=false to disable cross-encoder reranking.
RERANKER_ENABLED = os.environ.get("RERANKER_ENABLED", "true").strip().lower() != "false"
RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANK_OVERFETCH_FACTOR = 3

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
OPENAI_MODEL = _env("OPENAI_MODEL") or "gemini-3-pro-preview-litellm-gbl"

# ── Streamlit UI ──────────────────────────────────────────────────────────────
AGENT_BACKEND = _env("AGENT_BACKEND") or "pydantic"  # "pydantic" or "claude"

# ── Static constants (not env-driven) ────────────────────────────────────────
SECTION_ORDER = {
    "product_and_description": 0,
    "risks_and_return": 1,
    "costs": 2,
    "tail": 3,
}
