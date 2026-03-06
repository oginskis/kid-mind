"""Generate ground truth JSON files for chunking pipeline tests.

Usage:
    uv run python tests/generate_ground_truth.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from kid_mind.parser import process_pdf

log = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
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

# Key phrases to look for per section (EU-mandated headings / product terms)
_SECTION_PHRASES: dict[str, list[str]] = {
    "product_and_description": [
        "ISIN:",
        "Provider:",
    ],
    "risks_and_return": [
        "risk",
    ],
    "costs": [
        "cost",
    ],
    "tail": [],
}

# Additional key phrases to extract from chunk text
_PHRASE_PATTERNS = [
    r"What is this product",
    r"What are the risks",
    r"Performance Scenarios",
    r"What are the costs",
    r"How long should I hold",
    r"How can I complain",
    r"Other relevant information",
    r"unable to pay",
    r"Objectives and Investment Policy",
    r"Risk and Reward Profile",
    r"Past Performance",
    r"Charges",
    r"Practical Information",
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


def _extract_key_phrases(text: str) -> list[str]:
    """Extract key phrases found in the chunk text."""
    found = []
    for pattern in _PHRASE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(pattern)
    return found


def generate_ground_truth(provider: str, isin: str) -> dict:
    """Process a PDF and generate ground truth JSON structure."""
    pdf = PDFS_DIR / f"{provider}__{isin}.pdf"
    if not pdf.exists():
        raise FileNotFoundError(f"PDF fixture not found: {pdf}")

    log.info("Processing %s/%s...", provider, isin)
    chunks = process_pdf(pdf, isin, provider)

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

    return {
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_pdf_sha256": _sha256_file(pdf),
        "isin": isin,
        "provider": provider,
        "chunk_count": len(chunks),
        "chunks": gt_chunks,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)

    for provider, isin in TEST_CASES:
        gt = generate_ground_truth(provider, isin)
        out_path = GROUND_TRUTH_DIR / f"{provider}__{isin}.json"
        out_path.write_text(json.dumps(gt, indent=2, ensure_ascii=False) + "\n")
        log.info("  -> %s: %d chunks", out_path.name, gt["chunk_count"])

    log.info("Ground truth files written to %s", GROUND_TRUTH_DIR)


if __name__ == "__main__":
    main()
