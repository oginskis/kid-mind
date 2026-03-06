"""Download PRIIPs KID PDFs for Vanguard, iShares, Xtrackers, and SPDR.

Reads ISINs from data/isins/<provider>.json (produced by discover_isins.py).
Downloads KID PDFs to data/kids/<provider>/<ISIN>.pdf.
Computes SHA-256 hash on download and stores it in the ISIN JSON entry.

Provider strategies (all direct HTTP — no Playwright needed):
  - Vanguard: direct HTTP GET via fund-docs.vanguard.com
  - SPDR: direct HTTP GET via ssga.com (requires ticker)
  - iShares: direct HTTP GET via blackrock.com (resolved via document search API)
  - Xtrackers: two-step HTTP — resolve GUID from download.dws.com listing, then fetch PDF

Usage:
    python download_kids.py                  # all providers
    python download_kids.py -p vanguard
    python download_kids.py -p spdr -m 10
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402
from config import (  # noqa: E402
    DATA_DIR,
    KIDS_DIR,
    MAX_RETRIES,
    MIN_PDF_SIZE,
    PDF_MAGIC,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    REQUEST_HEADERS,
    RETRY_BACKOFF_BASE,
    SPDR_KID_URL,
    VANGUARD_KID_URL,
    XTRACKERS_DOWNLOAD_URL,
    XTRACKERS_LISTING_URL,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _delay() -> None:
    """Random delay between requests for rate limiting."""
    time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))


def _validate_pdf(data: bytes) -> bool:
    """Check that data looks like a real PDF."""
    return data[:5] == PDF_MAGIC and len(data) >= MIN_PDF_SIZE


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_mtime_iso(path: Path) -> str:
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_isins(provider: str) -> list[dict]:
    path = DATA_DIR / f"{provider}.json"
    if not path.exists():
        log.error("No ISIN file for %s at %s — run discover_isins.py first", provider, path)
        return []
    data = json.loads(path.read_text())
    log.info("Loaded %d ISINs for %s", len(data), provider)
    return data


def _save_funds(provider: str, funds: list[dict]) -> None:
    """Save fund data (with metadata) back to the ISIN JSON file."""
    path = DATA_DIR / f"{provider}.json"
    cleaned = [{k: v for k, v in f.items() if v} for f in funds]
    path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n")


def _out_dir(provider: str) -> Path:
    d = KIDS_DIR / provider
    d.mkdir(parents=True, exist_ok=True)
    return d


def _already_downloaded(provider: str, isin: str) -> bool:
    pdf = KIDS_DIR / provider / f"{isin}.pdf"
    return pdf.exists() and pdf.stat().st_size >= MIN_PDF_SIZE


# ── HTTP download with retries ─────────────────────────────────────────────────


def _http_download_bytes(url: str) -> bytes | None:
    """Download a PDF via HTTP with retries and validation. Returns raw bytes or None."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = RETRY_BACKOFF_BASE**attempt
                log.warning("HTTP %d for %s — retrying in %.0fs", resp.status_code, url, wait)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                log.warning("HTTP %d for %s", resp.status_code, url)
                return None
            if not _validate_pdf(resp.content):
                log.warning("Invalid PDF from %s (size=%d, header=%r)", url, len(resp.content), resp.content[:10])
                return None
            return resp.content
        except requests.RequestException as e:
            wait = RETRY_BACKOFF_BASE**attempt
            log.warning("Request error for %s: %s — retrying in %.0fs", url, e, wait)
            time.sleep(wait)
    return None


# ── Provider URL builders ─────────────────────────────────────────────────────


def vanguard_url(isin: str) -> str:
    """Build the Vanguard KID download URL for a given ISIN."""
    return VANGUARD_KID_URL.format(isin_lower=isin.lower())


def spdr_url(isin: str, ticker: str) -> str:
    """Build the SPDR KID download URL for a given ISIN and ticker."""
    return SPDR_KID_URL.format(isin=isin, ticker=ticker.lower())


ISHARES_DOC_SEARCH_URL = "https://www.blackrock.com/varnish-api/library/search-documents"


def ishares_resolve_pdf_urls(isin: str) -> list[str]:
    """Resolve KID PDF URLs for an iShares fund via the BlackRock document API.

    Returns a list of URLs to try (eu-priips first, then gls-download fallback).
    """
    try:
        resp = requests.post(
            ISHARES_DOC_SEARCH_URL,
            headers={
                **REQUEST_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.blackrock.com",
            },
            data=f"siteId=walrus-kiid&locale=en-gb&keyword={isin}&rows=5&start=0",
            timeout=30,
        )
        if resp.status_code != 200:
            log.warning("iShares API: HTTP %d for %s", resp.status_code, isin)
            return []

        data = resp.json()
        docs = data.get("searchDocuments", [])
        if not docs:
            log.warning("iShares API: no documents found for %s", isin)
            return []

        dre_ref = docs[0].get("dreReference", "")
        if not dre_ref:
            return []

        filename = dre_ref.rsplit("/", 1)[-1]
        urls = []

        if filename.startswith("ucits_kiid-"):
            slug_part = filename[len("ucits_kiid-") :]
            isin_lower = isin.lower()
            # eu-priips variant: change prefix, remove country code before ISIN
            eu_slug = re.sub(rf"-[a-z]{{2}}-({isin_lower})", r"-\1", slug_part)
            urls.append(f"https://www.blackrock.com/uk/literature/kiid/eu-priips-{eu_slug}")
            # uk_priips variant: change prefix, keep country code
            urls.append(f"https://www.blackrock.com/uk/literature/kiid/uk_priips-{slug_part}")
            # gls-download fallback: use original filename as-is
            urls.append(f"https://www.blackrock.com/gls-download/literature/kiid/{filename}")
        elif filename.startswith("uk_priips-"):
            urls.append(f"https://www.blackrock.com/uk/literature/kiid/{filename}")
            urls.append(f"https://www.blackrock.com/gls-download/literature/kiid/{filename}")
        elif filename.startswith("eu-priips-"):
            urls.append(f"https://www.blackrock.com/uk/literature/kiid/{filename}")
        else:
            urls.append(f"https://www.blackrock.com/gls-download/literature/kiid/{filename}")

        return urls

    except (requests.RequestException, ValueError) as e:
        log.warning("iShares API error for %s: %s", isin, e)
        return []


def xtrackers_resolve(isin: str) -> tuple[str, str | None] | None:
    """Fetch the Xtrackers listing page and resolve GUID + doc_date.

    Returns (guid, doc_date) on success, or None on failure.
    doc_date is parsed from the English KID filename (e.g. "2026-02-16") or None.
    """
    try:
        listing_url = XTRACKERS_LISTING_URL.format(isin=isin)
        resp = requests.get(listing_url, headers=REQUEST_HEADERS, timeout=30)
        if resp.status_code != 200:
            log.warning("Xtrackers: HTTP %d for listing %s", resp.status_code, isin)
            return None

        match = re.search(
            r'href="/download/asset/([0-9a-f-]{36})">[^<]*_en_[^<]*\.pdf',
            resp.text,
        )
        if not match:
            log.warning("Xtrackers: no English KID GUID found for %s", isin)
            return None

        guid = match.group(1)

        # Try to parse doc_date from English KID filename
        date_match = re.search(
            r'href="/download/asset/[0-9a-f-]{36}">([^<]*_en_(\d{4}-\d{2}-\d{2})\.pdf)',
            resp.text,
        )
        doc_date = date_match.group(2) if date_match else None

        return (guid, doc_date)
    except requests.RequestException as e:
        log.warning("Xtrackers: request error for %s: %s", isin, e)
        return None


# ── Provider downloaders ───────────────────────────────────────────────────────


def _download_and_record(fund: dict, data: bytes, **extra_meta: str) -> None:
    """Record metadata in the fund dict after a successful download."""
    fund["sha256"] = _sha256(data)
    fund["file_size"] = len(data)
    fund["downloaded_at"] = _now_iso()
    for k, v in extra_meta.items():
        if v:
            fund[k] = v


def download_vanguard(funds: list[dict], out_dir: Path) -> dict:
    """Download Vanguard KIDs via direct HTTP."""
    stats = {"total": len(funds), "downloaded": 0, "skipped": 0, "failed": 0}

    for fund in funds:
        isin = fund["isin"]
        if _already_downloaded("vanguard", isin):
            # Backfill hash for existing PDFs that don't have metadata yet
            if "sha256" not in fund:
                pdf_path = out_dir / f"{isin}.pdf"
                data = pdf_path.read_bytes()
                fund["sha256"] = _sha256(data)
                fund["file_size"] = len(data)
                fund["downloaded_at"] = _file_mtime_iso(pdf_path)
            stats["skipped"] += 1
            continue

        url = vanguard_url(isin)
        data = _http_download_bytes(url)
        if data is not None:
            dest = out_dir / f"{isin}.pdf"
            dest.write_bytes(data)
            _download_and_record(fund, data)
            log.info("Downloaded %s (%d KB)", isin, len(data) // 1024)
            stats["downloaded"] += 1
        else:
            stats["failed"] += 1

        _delay()

    return stats


def download_spdr(funds: list[dict], out_dir: Path) -> dict:
    """Download SPDR KIDs via direct HTTP. Requires ticker."""
    stats = {"total": len(funds), "downloaded": 0, "skipped": 0, "failed": 0, "no_ticker": 0}

    for fund in funds:
        isin = fund["isin"]
        ticker = fund.get("ticker", "")
        if not ticker:
            log.warning("SPDR: no ticker for %s — skipping", isin)
            stats["no_ticker"] += 1
            stats["failed"] += 1
            continue

        if _already_downloaded("spdr", isin):
            if "sha256" not in fund:
                pdf_path = out_dir / f"{isin}.pdf"
                data = pdf_path.read_bytes()
                fund["sha256"] = _sha256(data)
                fund["file_size"] = len(data)
                fund["downloaded_at"] = _file_mtime_iso(pdf_path)
            stats["skipped"] += 1
            continue

        url = spdr_url(isin, ticker)
        data = _http_download_bytes(url)
        if data is not None:
            dest = out_dir / f"{isin}.pdf"
            dest.write_bytes(data)
            _download_and_record(fund, data)
            log.info("Downloaded %s (%d KB)", isin, len(data) // 1024)
            stats["downloaded"] += 1
        else:
            stats["failed"] += 1

        _delay()

    return stats


def download_ishares(funds: list[dict], out_dir: Path) -> dict:
    """Download iShares KIDs via BlackRock document search API."""
    stats = {"total": len(funds), "downloaded": 0, "skipped": 0, "failed": 0}

    for fund in funds:
        isin = fund["isin"]
        if _already_downloaded("ishares", isin):
            if "sha256" not in fund:
                pdf_path = out_dir / f"{isin}.pdf"
                data = pdf_path.read_bytes()
                fund["sha256"] = _sha256(data)
                fund["file_size"] = len(data)
                fund["downloaded_at"] = _file_mtime_iso(pdf_path)
            stats["skipped"] += 1
            continue

        dest = out_dir / f"{isin}.pdf"
        urls = ishares_resolve_pdf_urls(isin)

        downloaded = False
        for url in urls:
            data = _http_download_bytes(url)
            if data is not None:
                dest.write_bytes(data)
                _download_and_record(fund, data)
                log.info("Downloaded %s (%d KB)", isin, len(data) // 1024)
                stats["downloaded"] += 1
                downloaded = True
                break

        if not downloaded:
            stats["failed"] += 1

        _delay()

    return stats


def download_xtrackers(funds: list[dict], out_dir: Path) -> dict:
    """Download Xtrackers KIDs via direct HTTP from download.dws.com."""
    stats = {"total": len(funds), "downloaded": 0, "skipped": 0, "failed": 0}

    for fund in funds:
        isin = fund["isin"]
        if _already_downloaded("xtrackers", isin):
            if "sha256" not in fund:
                pdf_path = out_dir / f"{isin}.pdf"
                data = pdf_path.read_bytes()
                fund["sha256"] = _sha256(data)
                fund["file_size"] = len(data)
                fund["downloaded_at"] = _file_mtime_iso(pdf_path)
            stats["skipped"] += 1
            continue

        dest = out_dir / f"{isin}.pdf"

        result = xtrackers_resolve(isin)
        if result is None:
            stats["failed"] += 1
            _delay()
            continue

        guid, doc_date = result
        pdf_url = XTRACKERS_DOWNLOAD_URL.format(guid=guid)
        data = _http_download_bytes(pdf_url)
        if data is not None:
            dest.write_bytes(data)
            _download_and_record(fund, data, doc_date=doc_date or "")
            log.info("Downloaded %s (%d KB)", isin, len(data) // 1024)
            stats["downloaded"] += 1
        else:
            stats["failed"] += 1

        _delay()

    return stats


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Download PRIIPs KID PDFs")
    parser.add_argument(
        "--provider",
        "-p",
        choices=["vanguard", "ishares", "xtrackers", "spdr"],
        help="Download for a single provider (default: all sequentially)",
    )
    parser.add_argument(
        "--max",
        "-m",
        type=int,
        default=0,
        help="Max PDFs to download per provider (0 = unlimited)",
    )
    args = parser.parse_args()

    providers = [args.provider] if args.provider else ["vanguard", "ishares", "xtrackers", "spdr"]

    dispatch = {
        "vanguard": download_vanguard,
        "ishares": download_ishares,
        "xtrackers": download_xtrackers,
        "spdr": download_spdr,
    }

    all_stats: dict[str, dict] = {}

    for provider in providers:
        log.info("=" * 60)
        log.info("Downloading KIDs for %s", provider)
        log.info("=" * 60)

        funds = _load_isins(provider)
        if not funds:
            all_stats[provider] = {"total": 0, "downloaded": 0, "skipped": 0, "failed": 0}
            continue

        if args.max > 0:
            funds = funds[: args.max]

        out_dir = _out_dir(provider)

        try:
            stats = dispatch[provider](funds, out_dir)
            all_stats[provider] = stats
        except Exception:
            log.exception("Error downloading KIDs for %s", provider)
            all_stats[provider] = {"error": True}

        _save_funds(provider, funds)

    # ── Summary ────────────────────────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("DOWNLOAD SUMMARY")
    log.info("=" * 60)
    for provider, stats in all_stats.items():
        if "error" in stats:
            log.info("  %-12s: ERROR", provider)
        else:
            log.info(
                "  %-12s: %d downloaded, %d skipped (already exist), %d failed / %d total",
                provider,
                stats.get("downloaded", 0),
                stats.get("skipped", 0),
                stats.get("failed", 0),
                stats.get("total", 0),
            )
            if stats.get("no_ticker"):
                log.info("               (%d had no ticker)", stats["no_ticker"])


if __name__ == "__main__":
    main()
