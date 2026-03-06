"""Integration tests: process_pdf() output vs committed ground truth JSON.

All test PDFs are processed once via the session-scoped `pipeline_results` fixture,
then reused by all parametrized tests. Each test case runs independently.

Content correctness tests (TestContentCorrectness) verify that EU-mandated content
lands in the correct semantic section — these are NOT ground-truth-circular; they
assert structural invariants that must hold for any correct KID extraction.
"""

from __future__ import annotations

import re

import pytest

from tests.conftest import TEST_CASES, load_ground_truth, pdf_path, sha256_file


@pytest.mark.parametrize(("provider", "isin"), TEST_CASES)
class TestChunkPipeline:
    """Ground truth tests for the chunking pipeline."""

    def test_pdf_sha256_unchanged(self, provider: str, isin: str) -> None:
        """Source PDF hasn't been replaced by provider."""
        gt = load_ground_truth(provider, isin)
        actual_sha = sha256_file(pdf_path(provider, isin))
        assert actual_sha == gt["_pdf_sha256"], (
            f"PDF hash mismatch for {isin} — fixture PDF may have been replaced. "
            f"Re-run tests/generate_ground_truth.py to update."
        )

    def test_chunk_count(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Section splitting produces expected number of chunks."""
        gt = load_ground_truth(provider, isin)
        chunks = pipeline_results[(provider, isin)]
        assert len(chunks) == gt["chunk_count"], f"{isin}: expected {gt['chunk_count']} chunks, got {len(chunks)}"

    def test_section_names_and_order(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Section names and ordering match ground truth."""
        gt = load_ground_truth(provider, isin)
        chunks = pipeline_results[(provider, isin)]
        actual_sections = [c["section"] for c in chunks]
        expected_sections = [c["section"] for c in gt["chunks"]]
        assert actual_sections == expected_sections

    def test_chunk_ids(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Chunk IDs match ground truth."""
        gt = load_ground_truth(provider, isin)
        chunks = pipeline_results[(provider, isin)]
        actual_ids = [c["id"] for c in chunks]
        expected_ids = [c["id"] for c in gt["chunks"]]
        assert actual_ids == expected_ids

    def test_metadata_match(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Metadata fields match ground truth exactly."""
        gt = load_ground_truth(provider, isin)
        chunks = pipeline_results[(provider, isin)]
        for actual, expected in zip(chunks, gt["chunks"], strict=True):
            assert actual["metadata"] == expected["metadata"], f"Metadata mismatch in chunk {expected['id']}"

    def test_text_length_within_tolerance(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Text length within 10% of ground truth (tolerates minor Docling changes)."""
        gt = load_ground_truth(provider, isin)
        chunks = pipeline_results[(provider, isin)]
        for actual, expected in zip(chunks, gt["chunks"], strict=True):
            actual_len = len(actual["text"])
            expected_len = expected["text_length"]
            tolerance = max(expected_len * 0.1, 50)
            assert abs(actual_len - expected_len) <= tolerance, (
                f"Text length drift in chunk {expected['id']}: expected ~{expected_len}, got {actual_len}"
            )

    def test_key_phrases_present(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """EU-mandated headings and product terms appear in correct chunks."""
        gt = load_ground_truth(provider, isin)
        chunks = pipeline_results[(provider, isin)]
        for actual, expected in zip(chunks, gt["chunks"], strict=True):
            for phrase in expected.get("key_phrases", []):
                assert phrase.lower() in actual["text"].lower(), (
                    f"Missing key phrase '{phrase}' in chunk {expected['id']}"
                )

    def test_risk_level_present(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Every chunk has a valid risk_level (1-7) in metadata."""
        chunks = pipeline_results[(provider, isin)]
        for chunk in chunks:
            rl = chunk["metadata"].get("risk_level")
            assert rl is not None, f"Chunk {chunk['id']} missing risk_level"
            assert 1 <= rl <= 7, f"Chunk {chunk['id']} has invalid risk_level={rl}"

    def test_metadata_prefix_in_text(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Metadata prefix line is present at the start of each chunk's text."""
        chunks = pipeline_results[(provider, isin)]
        for chunk in chunks:
            assert chunk["text"].startswith(f"ISIN: {isin}"), f"Chunk {chunk['id']} missing metadata prefix"
            assert f"Provider: {provider}" in chunk["text"].split("\n")[0]


# ── Content correctness tests ────────────────────────────────────────────────
# These tests assert structural invariants of EU PRIIPs KIDs — they do NOT
# depend on ground truth JSON and will catch section mis-placement bugs.

# SRI patterns: text that MUST appear in risks_and_return
# Covers PRIIPs ("classified this product as X out of 7") and
# old KIID format ("Fund is rated <word> due to")
_SRI_RE = re.compile(
    r"(?:classified\s+this\s+(?:product|fund)\s+as\s+\d\s+out\s+of\s+7"
    r"|summary\s+risk\s+indicator"
    r"|(?:Fund|product)\s+is\s+rated\s+\w+\s+due\s+to)",
    re.IGNORECASE,
)

# Cost patterns: text that MUST appear in costs section
# Covers PRIIPs ("entry cost") and old KIID ("entry charge", "ongoing charges")
_COST_RE = re.compile(
    r"(?:entry\s+cost|exit\s+cost|ongoing\s+cost|total\s+cost|reduction\s+in\s+yield"
    r"|entry.+?charge|exit.+?charge|ongoing\s+charge)",
    re.IGNORECASE,
)

# Performance / risk data pattern: MUST appear in risks_and_return
# Covers PRIIPs ("Performance Scenarios", "stress") and old KIID ("Past Performance")
_PERF_RE = re.compile(
    r"(?:performance\s+scenario|stress\s+scenario|unfavourable|moderate|favourable"
    r"|past\s+performance)",
    re.IGNORECASE,
)


def _chunk_by_section(chunks: list[dict], section: str) -> dict | None:
    """Return the first chunk matching a section name, or None."""
    for c in chunks:
        if c["section"] == section:
            return c
    return None


def _chunks_by_section(chunks: list[dict], section: str) -> list[dict]:
    """Return all chunks matching a section name."""
    return [c for c in chunks if c["section"] == section]


@pytest.mark.parametrize(("provider", "isin"), TEST_CASES)
class TestContentCorrectness:
    """Content correctness: verify EU-mandated content lands in the right section.

    These tests are independent of ground truth JSON — they assert structural
    invariants that must hold for any correctly parsed KID/KIID.
    """

    def test_sri_in_risks_section(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """SRI risk classification text must be in risks_and_return, not elsewhere."""
        chunks = pipeline_results[(provider, isin)]
        risk_chunks = _chunks_by_section(chunks, "risks_and_return")
        assert risk_chunks, f"{isin}: missing risks_and_return chunk"
        combined = " ".join(c["text"] for c in risk_chunks)
        assert _SRI_RE.search(combined), f"{isin}: SRI classification text not found in risks_and_return chunks"

    def test_sri_not_in_costs(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """SRI risk classification text must NOT appear in the costs chunk."""
        chunks = pipeline_results[(provider, isin)]
        costs = _chunk_by_section(chunks, "costs")
        if costs is None:
            pytest.skip(f"{isin}: no costs chunk")
        assert not _SRI_RE.search(costs["text"]), f"{isin}: SRI classification text leaked into costs chunk"

    def test_sri_not_in_product(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """SRI risk classification text must NOT appear in product_and_description."""
        chunks = pipeline_results[(provider, isin)]
        for product_chunk in _chunks_by_section(chunks, "product_and_description"):
            assert not _SRI_RE.search(product_chunk["text"]), (
                f"{isin}: SRI classification text leaked into product_and_description chunk"
            )

    def test_cost_data_in_costs_section(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Cost/fee data must appear in the costs chunks."""
        chunks = pipeline_results[(provider, isin)]
        cost_chunks = _chunks_by_section(chunks, "costs")
        assert cost_chunks, f"{isin}: missing costs chunk"
        combined = " ".join(c["text"] for c in cost_chunks)
        assert _COST_RE.search(combined), f"{isin}: no cost/fee data found in costs chunks"

    def test_performance_scenarios_in_risks(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Performance scenario data must be in risks_and_return."""
        chunks = pipeline_results[(provider, isin)]
        risk_chunks = _chunks_by_section(chunks, "risks_and_return")
        assert risk_chunks, f"{isin}: missing risks_and_return chunk"
        combined = " ".join(c["text"] for c in risk_chunks)
        assert _PERF_RE.search(combined), f"{isin}: no performance scenario data found in risks_and_return chunks"

    def test_product_name_in_product_section(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Product name from metadata must appear in product_and_description chunk."""
        chunks = pipeline_results[(provider, isin)]
        product_chunks = _chunks_by_section(chunks, "product_and_description")
        assert product_chunks, f"{isin}: missing product_and_description chunk"
        product_text = " ".join(c["text"] for c in product_chunks).lower()
        product_name = chunks[0]["metadata"].get("product_name", "")
        assert product_name, f"{isin}: empty product_name in metadata"
        # Check first significant word (>=4 chars) from product name appears in product text
        significant_words = [w for w in product_name.split() if len(w) >= 4]
        assert any(w.lower() in product_text for w in significant_words), (
            f"{isin}: product name '{product_name}' not found in product_and_description"
        )

    def test_isin_in_product_section(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """ISIN must appear in product_and_description (via metadata prefix)."""
        chunks = pipeline_results[(provider, isin)]
        product_chunks = _chunks_by_section(chunks, "product_and_description")
        assert product_chunks, f"{isin}: missing product_and_description chunk"
        assert any(isin in c["text"] for c in product_chunks), (
            f"{isin}: ISIN not found in product_and_description chunk"
        )

    def test_tail_chunk_exists(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Every KID must produce a tail chunk with complaints/holding info."""
        chunks = pipeline_results[(provider, isin)]
        tail = _chunk_by_section(chunks, "tail")
        assert tail is not None, f"{isin}: missing tail chunk"

    def test_four_section_structure(self, provider: str, isin: str, pipeline_results: dict) -> None:
        """Every KID should produce exactly 4 semantic sections."""
        chunks = pipeline_results[(provider, isin)]
        sections = {c["section"] for c in chunks}
        expected = {"product_and_description", "risks_and_return", "costs", "tail"}
        assert sections == expected, f"{isin}: expected sections {expected}, got {sections}"
