"""CLI runner for KID PDF chunking pipeline.

Orchestrates batch processing of KID PDFs: multithreaded PDF→chunk conversion,
optional ChromaDB upsert, and optional JSON debug dump.

Usage:
    uv run python chunk_kids_cli.py                              # all providers
    uv run python chunk_kids_cli.py -p vanguard                  # single provider
    uv run python chunk_kids_cli.py -p vanguard -m 10            # limit 10 PDFs
    uv run python chunk_kids_cli.py --dump-json                  # write debug JSON to data/chunks/
    uv run python chunk_kids_cli.py --skip-chromadb --dump-json  # JSON only, no ChromaDB needed
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from kid_mind.parser import extract_kid_date, extract_launch_year, process_pdf
from kid_mind.tools import CHROMADB_COLLECTION, CHROMADB_HOST, CHROMADB_PORT, create_embedding_function

# Mutable collection name — overridden by --collection CLI flag
_collection_name: str = CHROMADB_COLLECTION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Suppress noisy HTTP request logs from httpx, chromadb, and docling internals
for _noisy in ("httpx", "chromadb", "docling"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ── Paths (relative to project root) ─────────────────────────────────────────
DATA_DIR = Path("data") / "isins"
KIDS_DIR = Path("data") / "kids"
CHUNKS_DIR = Path("data") / "chunks"

# ── Batch ────────────────────────────────────────────────────────────────────
CHROMADB_BATCH_SIZE = 100
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "3"))


# ── ISIN record lookup ────────────────────────────────────────────────────────


def _load_isin_index(provider: str) -> dict[str, dict]:
    """Load ISIN JSON for a provider and index by ISIN."""
    path = DATA_DIR / f"{provider}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {rec["isin"]: rec for rec in data}


# ── ChromaDB storage ─────────────────────────────────────────────────────────

_chromadb_collection = None
_chromadb_lock = threading.Lock()


def _get_chromadb_collection() -> object:
    """Return the ChromaDB collection, initializing the client once (thread-safe)."""
    global _chromadb_collection  # noqa: PLW0603
    if _chromadb_collection is not None:
        return _chromadb_collection
    with _chromadb_lock:
        if _chromadb_collection is not None:
            return _chromadb_collection
        import chromadb

        log.info("Connecting to ChromaDB at %s:%d ...", CHROMADB_HOST, CHROMADB_PORT)
        client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        ef = create_embedding_function()
        _chromadb_collection = client.get_or_create_collection(
            name=_collection_name,
            embedding_function=ef,
        )
        return _chromadb_collection


_upsert_lock = threading.Lock()


def _upsert_chunks(chunks: list[dict], batch_size: int = 10) -> None:
    """Upsert a single PDF's chunks to ChromaDB (thread-safe, batched)."""
    if not chunks:
        return
    collection = _get_chromadb_collection()
    with _upsert_lock:
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            collection.upsert(
                ids=[c["id"] for c in batch],
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
            )


# ── JSON dump ─────────────────────────────────────────────────────────────────


def _dump_json(all_chunks: list[dict], provider: str | None) -> None:
    """Write chunks to data/chunks/ as JSON for debugging."""
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"_{provider}" if provider else "_all"
    out_path = CHUNKS_DIR / f"chunks{suffix}.json"
    out_path.write_text(json.dumps(all_chunks, indent=2, ensure_ascii=False))
    log.info("Wrote %d chunks to %s", len(all_chunks), out_path)


# ── Metadata patching ────────────────────────────────────────────────────────


def _patch_metadata() -> None:
    """Patch launch_year and kid_date into existing ChromaDB chunks.

    Reads stored document text, runs extraction regexes, and upserts
    only the metadata changes — no re-processing through Docling.
    """
    collection = _get_chromadb_collection()
    total = collection.count()
    log.info("Fetching %d chunks from ChromaDB for metadata patching...", total)

    # Fetch all chunks in batches (ChromaDB has a default limit)
    all_ids = []
    all_docs = []
    all_metas = []
    batch_size = 5000
    offset = 0
    while offset < total:
        batch = collection.get(
            limit=batch_size,
            offset=offset,
            include=["documents", "metadatas"],
        )
        all_ids.extend(batch["ids"])
        all_docs.extend(batch["documents"])
        all_metas.extend(batch["metadatas"])
        offset += len(batch["ids"])
        if not batch["ids"]:
            break

    # Group by ISIN — extract once per ISIN from the concatenated text
    isin_texts: dict[str, list[str]] = {}
    isin_chunks: dict[str, list[int]] = {}  # ISIN → list of indices
    for idx, meta in enumerate(all_metas):
        isin = meta.get("isin", "")
        if not isin:
            continue
        isin_texts.setdefault(isin, []).append(all_docs[idx])
        isin_chunks.setdefault(isin, []).append(idx)

    log.info("Found %d unique ISINs across %d chunks", len(isin_texts), total)

    patched_isins = 0
    patched_chunks = 0
    for isin, texts in isin_texts.items():
        combined = "\n\n".join(texts)
        launch_year = extract_launch_year(combined)
        kid_date = extract_kid_date(combined)

        if launch_year is None and kid_date is None:
            continue

        patched_isins += 1
        indices = isin_chunks[isin]
        # Batch upsert for this ISIN
        batch_ids = []
        batch_metas = []
        for i in indices:
            meta = dict(all_metas[i])  # copy
            if launch_year is not None:
                meta["launch_year"] = launch_year
            if kid_date is not None:
                meta["kid_date"] = kid_date
            batch_ids.append(all_ids[i])
            batch_metas.append(meta)

        for j in range(0, len(batch_ids), CHROMADB_BATCH_SIZE):
            end = j + CHROMADB_BATCH_SIZE
            collection.update(
                ids=batch_ids[j:end],
                metadatas=batch_metas[j:end],
            )
        patched_chunks += len(indices)

    log.info(
        "Patched %d ISIN(s) (%d chunks) with launch_year/kid_date metadata",
        patched_isins,
        patched_chunks,
    )


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse KID PDFs and store chunks in ChromaDB")
    parser.add_argument(
        "--provider",
        "-p",
        choices=["vanguard", "ishares", "xtrackers", "spdr"],
        help="Process a single provider (default: all)",
    )
    parser.add_argument(
        "--max",
        "-m",
        type=int,
        default=0,
        help="Max PDFs to process per provider (0 = unlimited)",
    )
    parser.add_argument(
        "--dump-json",
        action="store_true",
        help="Write chunks to data/chunks/ as JSON for debugging",
    )
    parser.add_argument(
        "--skip-chromadb",
        action="store_true",
        help="Skip ChromaDB upsert (useful with --dump-json)",
    )
    parser.add_argument(
        "--patch-metadata",
        action="store_true",
        help="Patch launch_year and kid_date metadata on existing ChromaDB chunks (no re-indexing)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help=f"ChromaDB collection name (default: {CHROMADB_COLLECTION}). "
        "Use a different name to rebuild without touching the live collection.",
    )
    args = parser.parse_args()

    # Override collection name if specified
    if args.collection:
        global _collection_name  # noqa: PLW0603
        _collection_name = args.collection
        log.info("Using collection: %s", args.collection)

    if args.patch_metadata:
        _patch_metadata()
        return

    providers = [args.provider] if args.provider else ["vanguard", "ishares", "xtrackers", "spdr"]

    all_chunks: list[dict] = []
    stats: dict[str, dict] = {}

    grand_total_pdfs = 0
    grand_processed = 0
    t_start = time.monotonic()

    # Pre-scan to get total PDF count across all providers for progress display
    provider_pdfs: dict[str, list[Path]] = {}
    for provider in providers:
        kids_dir = KIDS_DIR / provider
        if not kids_dir.exists():
            provider_pdfs[provider] = []
            continue
        pdfs = sorted(kids_dir.glob("*.pdf"))
        if args.max > 0:
            pdfs = pdfs[: args.max]
        provider_pdfs[provider] = pdfs
        grand_total_pdfs += len(pdfs)

    for provider in providers:
        pdfs = provider_pdfs[provider]
        isin_index = _load_isin_index(provider)

        if not pdfs:
            log.warning("No KID PDFs for %s", provider)
            stats[provider] = {"total": 0, "processed": 0, "failed": 0, "chunks": 0}
            continue

        log.info("")
        log.info("=" * 60)
        log.info("%s — %d PDFs to process", provider.upper(), len(pdfs))
        log.info("=" * 60)

        provider_stats = {"total": len(pdfs), "processed": 0, "failed": 0, "chunks": 0}

        upsert = not args.skip_chromadb

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for pdf in pdfs:
                isin = pdf.stem
                isin_record = isin_index.get(isin)
                future = executor.submit(process_pdf, pdf, isin, provider, isin_record)
                futures[future] = (isin, isin_record)

            for future in as_completed(futures):
                isin, isin_record = futures[future]
                try:
                    chunks = future.result()
                    if upsert:
                        _upsert_chunks(chunks)
                    all_chunks.extend(chunks)
                    provider_stats["processed"] += 1
                    provider_stats["chunks"] += len(chunks)
                    grand_processed += 1

                    # Build a human-friendly label: ISIN + product name if available
                    product_name = ""
                    if chunks and chunks[0].get("metadata", {}).get("product_name"):
                        product_name = chunks[0]["metadata"]["product_name"]
                    elif isin_record and isin_record.get("name"):
                        product_name = isin_record["name"]
                    label = f"{isin} ({product_name})" if product_name else isin

                    # Progress with ETA
                    elapsed = time.monotonic() - t_start
                    rate = grand_processed / elapsed if elapsed > 0 else 0
                    remaining = (grand_total_pdfs - grand_processed) / rate if rate > 0 else 0
                    eta_min = remaining / 60

                    action = "upserted" if upsert else "chunked"
                    log.info(
                        "[%d/%d] %s — %d chunks %s  (%.1f PDFs/min, ETA %.0f min)",
                        grand_processed,
                        grand_total_pdfs,
                        label,
                        len(chunks),
                        action,
                        rate * 60,
                        eta_min,
                    )
                except (RuntimeError, ValueError, OSError):
                    grand_processed += 1
                    provider_stats["failed"] += 1
                    log.exception("[%d/%d] %s — FAILED", grand_processed, grand_total_pdfs, isin)

        stats[provider] = provider_stats

    # ── Output ────────────────────────────────────────────────────────────────
    if args.dump_json:
        _dump_json(all_chunks, args.provider)

    # ── Summary ───────────────────────────────────────────────────────────────
    total_elapsed = time.monotonic() - t_start
    elapsed_min = total_elapsed / 60

    log.info("")
    log.info("=" * 60)
    log.info("CHUNKING SUMMARY  (%.1f min elapsed)", elapsed_min)
    log.info("=" * 60)
    total_chunks = 0
    for provider, s in stats.items():
        log.info(
            "  %-12s  %d processed, %d failed / %d total  →  %d chunks",
            provider,
            s["processed"],
            s["failed"],
            s["total"],
            s["chunks"],
        )
        total_chunks += s["chunks"]

    total_processed = sum(s["processed"] for s in stats.values())
    total_failed = sum(s["failed"] for s in stats.values())
    log.info("  %-12s  %d processed, %d failed  →  %d chunks", "TOTAL", total_processed, total_failed, total_chunks)
    if elapsed_min > 0 and total_processed:
        log.info("  Throughput:   %.1f PDFs/min", total_processed / elapsed_min)
    if not args.skip_chromadb and total_chunks:
        log.info("  ChromaDB:     %d chunks in collection '%s'", _get_chromadb_collection().count(), _collection_name)


if __name__ == "__main__":
    main()
