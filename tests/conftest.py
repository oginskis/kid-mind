"""Shared fixtures and helpers for KID chunking pipeline tests."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import chromadb
import pytest
from dotenv import load_dotenv

# Load .env from project root before any test code runs
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

# Force local sentence-transformers embeddings in tests — tests must not
# depend on external API endpoints (Ollama, OpenAI, etc.)
for _key in (
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "EMBEDDING_API_KEY",
    "EMBEDDING_API_BASE",
    "EMBEDDING_MODEL",
    "GEMINI_API_KEY",
):
    os.environ.pop(_key, None)

import kid_mind.config  # noqa: E402

kid_mind.config.OPENAI_API_KEY = None
kid_mind.config.OPENAI_API_BASE = None
kid_mind.config.EMBEDDING_API_KEY = None
kid_mind.config.EMBEDDING_API_BASE = None
kid_mind.config.EMBEDDING_MODEL = None

import kid_mind.tools as tools_module  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PDFS_DIR = FIXTURES_DIR / "pdfs"
GROUND_TRUTH_DIR = FIXTURES_DIR / "ground_truth"

TEST_CASES = [
    ("vanguard", "IE00004S2680"),
    ("ishares", "IE0030308773"),
    ("ishares", "GB00B08HD364"),
    ("xtrackers", "LU0779800910"),
    ("spdr", "IE000191HKF0"),
    ("xtrackers", "DE000A1E0HR8"),
    ("vanguard", "IE0001RDRUG3"),
    ("xtrackers", "DE000A1EK0G3"),
    ("spdr", "IE00059GZ051"),
]


def pdf_path(provider: str, isin: str) -> Path:
    """Return path to a test PDF fixture."""
    return PDFS_DIR / f"{provider}__{isin}.pdf"


def ground_truth_path(provider: str, isin: str) -> Path:
    """Return path to a ground truth JSON file."""
    return GROUND_TRUTH_DIR / f"{provider}__{isin}.json"


def load_ground_truth(provider: str, isin: str) -> dict:
    """Load and return parsed ground truth JSON for a test case."""
    path = ground_truth_path(provider, isin)
    return json.loads(path.read_text())


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


@pytest.fixture(scope="session")
def pipeline_results() -> dict[tuple[str, str], list[dict]]:
    """Process all test PDFs once and cache results for the session.

    Returns a dict mapping (provider, isin) to process_pdf() output.
    Ground truth JSON is regenerated from the same results to avoid
    non-determinism from separate semantic chunking API calls.
    """
    from kid_mind.parser import process_pdf
    from tests.generate_ground_truth import _extract_key_phrases, _sha256_file

    results = {}
    for provider, isin in TEST_CASES:
        path = pdf_path(provider, isin)
        results[(provider, isin)] = process_pdf(path, isin, provider)

    # Regenerate ground truth from these same results so tests are self-consistent
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    for (provider, isin), chunks in results.items():
        pdf = pdf_path(provider, isin)
        gt_chunks = []
        for chunk in chunks:
            key_phrases = _extract_key_phrases(chunk["text"])
            gt_chunks.append(
                {
                    "id": chunk["id"],
                    "section": chunk["section"],
                    "sub_index": chunk["sub_index"],
                    "text": chunk["text"],
                    "text_length": len(chunk["text"]),
                    "metadata": chunk["metadata"],
                    "key_phrases": key_phrases,
                }
            )

        gt = {
            "_generated_at": datetime.now(timezone.utc).isoformat(),
            "_pdf_sha256": _sha256_file(pdf),
            "isin": isin,
            "provider": provider,
            "chunk_count": len(chunks),
            "chunks": gt_chunks,
        }
        out_path = GROUND_TRUTH_DIR / f"{provider}__{isin}.json"
        out_path.write_text(json.dumps(gt, indent=2, ensure_ascii=False) + "\n")

    return results


@pytest.fixture(scope="session")
def chromadb_collection(pipeline_results):
    """In-memory ChromaDB collection seeded with all test fixture chunks.

    Patches tools._collection so tool functions use this collection directly.
    Restored to None on teardown.
    """
    client = chromadb.EphemeralClient()
    ef = tools_module.create_embedding_function()
    collection = client.get_or_create_collection(
        name=tools_module.CHROMADB_COLLECTION,
        embedding_function=ef,
    )

    # Gather all chunks and upsert in batches (embedding API has a 20k token limit)
    ids = []
    documents = []
    metadatas = []
    for chunks in pipeline_results.values():
        for chunk in chunks:
            ids.append(chunk["id"])
            documents.append(chunk["text"])
            metadatas.append(chunk["metadata"])

    batch_size = 10
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i : i + batch_size],
            documents=documents[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
        )

    # Patch the module-level singleton
    tools_module._collection = collection
    yield collection
    tools_module._collection = None
