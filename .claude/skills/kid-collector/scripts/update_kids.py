"""Detect new and updated KID documents across all providers.

Reads fund data (including metadata) from data/isins/<provider>.json,
checks for new/changed KIDs, and updates the same file.

Update detection strategies:
  - Xtrackers: lightweight date check via listing page (avoids full re-download)
  - Vanguard, SPDR, iShares: re-download to memory + SHA-256 hash comparison

Usage:
    python update_kids.py                     # check all providers
    python update_kids.py -p xtrackers        # single provider
    python update_kids.py -p vanguard -m 5    # limit docs checked
    python update_kids.py --backfill          # add metadata to entries from existing PDFs
    python update_kids.py --force             # ignore cached metadata, re-check all
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    KIDS_DIR,
    XTRACKERS_DOWNLOAD_URL,
)
from download_kids import (
    _delay,
    _file_mtime_iso,
    _http_download_bytes,
    _load_isins,
    _now_iso,
    _out_dir,
    _save_funds,
    _sha256,
    ishares_resolve_pdf_urls,
    spdr_url,
    vanguard_url,
    xtrackers_resolve,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

PROVIDERS = ["vanguard", "ishares", "xtrackers", "spdr"]


# ── Per-provider update logic ─────────────────────────────────────────────────


def _download_bytes_for_provider(provider: str, fund: dict) -> bytes | None:
    """Download KID PDF bytes for a fund using the provider-specific URL strategy."""
    isin = fund["isin"]

    if provider == "vanguard":
        url = vanguard_url(isin)
        return _http_download_bytes(url)

    elif provider == "spdr":
        ticker = fund.get("ticker", "")
        if not ticker:
            log.warning("SPDR: no ticker for %s — skipping", isin)
            return None
        url = spdr_url(isin, ticker)
        return _http_download_bytes(url)

    elif provider == "ishares":
        for url in ishares_resolve_pdf_urls(isin):
            data = _http_download_bytes(url)
            if data is not None:
                return data
        return None

    elif provider == "xtrackers":
        result = xtrackers_resolve(isin)
        if result is None:
            return None
        guid, _doc_date = result
        pdf_url = XTRACKERS_DOWNLOAD_URL.format(guid=guid)
        return _http_download_bytes(pdf_url)

    return None


def _check_xtrackers(isin: str, fund: dict) -> tuple[str | None, str | None]:
    """Check Xtrackers listing page for doc_date change.

    Returns (guid, doc_date) if check was performed, or (None, None) on failure.
    If doc_date matches existing fund metadata, guid will be None (skip re-download).
    """
    result = xtrackers_resolve(isin)
    if result is None:
        return (None, None)

    guid, doc_date = result

    # If fund already has a matching doc_date, skip re-download
    if doc_date and fund.get("doc_date") == doc_date:
        return (None, doc_date)  # guid=None signals "unchanged"

    return (guid, doc_date)


# ── Core update logic ─────────────────────────────────────────────────────────


def _update_provider(
    provider: str,
    funds: list[dict],
    max_docs: int = 0,
    force: bool = False,
) -> dict:
    """Check one provider for new/updated KIDs.

    Modifies fund dicts in place with updated metadata.
    Returns stats dict: {new, updated, unchanged, failed, total}.
    """
    stats = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0, "total": 0}

    if not funds:
        return stats

    funds_to_check = funds[:max_docs] if max_docs > 0 else funds
    stats["total"] = len(funds_to_check)
    out_dir = _out_dir(provider)

    for fund in funds_to_check:
        isin = fund["isin"]
        pdf_path = out_dir / f"{isin}.pdf"
        has_meta = "sha256" in fund

        # Case 1: PDF exists on disk but no metadata — backfill hash
        if not has_meta and pdf_path.exists() and pdf_path.stat().st_size > 0:
            data = pdf_path.read_bytes()
            fund["sha256"] = _sha256(data)
            fund["file_size"] = len(data)
            fund["downloaded_at"] = _file_mtime_iso(pdf_path)
            has_meta = True
            log.info("Backfilled metadata for %s/%s", provider, isin)

        # Case 2: New ISIN — not on disk (or missing/tiny file)
        if not pdf_path.exists() or pdf_path.stat().st_size < 1:
            xt_doc_date = None
            if provider == "xtrackers":
                result = xtrackers_resolve(isin)
                if result is None:
                    stats["failed"] += 1
                    _delay()
                    continue
                guid, xt_doc_date = result
                data = _http_download_bytes(XTRACKERS_DOWNLOAD_URL.format(guid=guid))
            else:
                data = _download_bytes_for_provider(provider, fund)

            if data is not None:
                pdf_path.write_bytes(data)
                fund["sha256"] = _sha256(data)
                fund["file_size"] = len(data)
                fund["downloaded_at"] = _now_iso()
                if xt_doc_date:
                    fund["doc_date"] = xt_doc_date
                log.info("NEW: %s/%s (%d KB)", provider, isin, len(data) // 1024)
                stats["new"] += 1
            else:
                stats["failed"] += 1
            _delay()
            continue

        # Case 3: Existing ISIN — check for updates
        xt_update_doc_date = None
        if provider == "xtrackers" and not force:
            # Lightweight date check
            guid, xt_update_doc_date = _check_xtrackers(isin, fund)

            if guid is None and xt_update_doc_date is not None:
                # Date matches — unchanged
                stats["unchanged"] += 1
                _delay()
                continue

            if guid is None and xt_update_doc_date is None:
                # Failed to resolve
                stats["failed"] += 1
                _delay()
                continue

            # Date differs or no stored date — re-download via GUID
            pdf_url = XTRACKERS_DOWNLOAD_URL.format(guid=guid)
            data = _http_download_bytes(pdf_url)
        else:
            # Vanguard/SPDR/iShares (or --force for Xtrackers): re-download + hash
            data = _download_bytes_for_provider(provider, fund)

        if data is None:
            stats["failed"] += 1
            _delay()
            continue

        new_hash = _sha256(data)
        if has_meta and new_hash == fund.get("sha256"):
            stats["unchanged"] += 1
        else:
            # Document has changed — write to disk
            pdf_path.write_bytes(data)
            now = _now_iso()
            if not fund.get("downloaded_at"):
                fund["downloaded_at"] = now
            fund["sha256"] = new_hash
            fund["file_size"] = len(data)
            fund["updated_at"] = now
            if xt_update_doc_date:
                fund["doc_date"] = xt_update_doc_date
            log.info("UPDATED: %s/%s (%d KB)", provider, isin, len(data) // 1024)
            stats["updated"] += 1

        _delay()

    return stats


# ── Backfill mode ─────────────────────────────────────────────────────────────


def _backfill(providers_to_run: list[str]) -> None:
    """Add metadata to ISIN entries from existing PDFs on disk."""
    total = 0

    for provider in providers_to_run:
        funds = _load_isins(provider)
        if not funds:
            continue

        provider_dir = KIDS_DIR / provider
        if not provider_dir.exists():
            continue

        count = 0
        for fund in funds:
            if "sha256" in fund:
                continue  # already has metadata

            isin = fund["isin"]
            pdf_path = provider_dir / f"{isin}.pdf"
            if not pdf_path.exists() or pdf_path.stat().st_size < 1:
                continue

            data = pdf_path.read_bytes()
            fund["sha256"] = _sha256(data)
            fund["file_size"] = len(data)
            fund["downloaded_at"] = _file_mtime_iso(pdf_path)

            # For Xtrackers, also fetch doc_date from listing page
            if provider == "xtrackers":
                result = xtrackers_resolve(isin)
                if result:
                    fund["doc_date"] = result[1]
                _delay()

            count += 1

        if count > 0:
            log.info("Backfilled %d entries for %s", count, provider)
            _save_funds(provider, funds)
        total += count

    log.info("Backfill complete: %d total entries updated", total)


# ── Summary report ────────────────────────────────────────────────────────────


def _print_report(all_stats: dict[str, dict]) -> None:
    totals = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0, "total": 0}

    log.info("KID UPDATE REPORT")

    for provider, stats in all_stats.items():
        suffix = " (date-check)" if provider == "xtrackers" else ""
        log.info(
            "  %-12s: %d new, %d updated, %d unchanged, %d failed / %d total%s",
            provider,
            stats["new"],
            stats["updated"],
            stats["unchanged"],
            stats["failed"],
            stats["total"],
            suffix,
        )
        for k in totals:
            totals[k] += stats[k]

    log.info(
        "  %-12s: %d new, %d updated, %d unchanged, %d failed / %d total",
        "TOTAL",
        totals["new"],
        totals["updated"],
        totals["unchanged"],
        totals["failed"],
        totals["total"],
    )


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Check for new and updated KID documents")
    parser.add_argument(
        "--provider",
        "-p",
        choices=PROVIDERS,
        help="Check a single provider (default: all)",
    )
    parser.add_argument(
        "--max",
        "-m",
        type=int,
        default=0,
        help="Max documents to check per provider (0 = unlimited)",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Add metadata to ISIN entries from existing PDFs",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-check all documents (ignore cached date/hash)",
    )
    args = parser.parse_args()

    providers = [args.provider] if args.provider else PROVIDERS

    if args.backfill:
        _backfill(providers)
        return

    all_stats: dict[str, dict] = {}

    for provider in providers:
        log.info("=" * 60)
        log.info("Checking %s for updates", provider)
        log.info("=" * 60)

        funds = _load_isins(provider)

        try:
            stats = _update_provider(provider, funds, args.max, args.force)
            all_stats[provider] = stats
        except Exception:
            log.exception("Error checking %s", provider)
            all_stats[provider] = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0, "total": 0}

        _save_funds(provider, funds)

    _print_report(all_stats)


if __name__ == "__main__":
    main()
