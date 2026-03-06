"""Shared configuration for KID document discovery and download."""

from __future__ import annotations

from pathlib import Path

# ── Project paths (relative to working directory) ─────────────────────────────
DATA_DIR = Path("data") / "isins"
KIDS_DIR = Path("data") / "kids"

# ── KID download URL templates ─────────────────────────────────────────────────
# Vanguard: direct HTTP – ISIN must be lowercase
VANGUARD_KID_URL = "https://fund-docs.vanguard.com/{isin_lower}_priipskid_en.pdf"

# SPDR: direct HTTP – needs ISIN (uppercase) and ticker
SPDR_KID_URL = (
    "https://www.ssga.com/library-content/kids?isin={isin}&documentType=kid&country=ie&language=en_gb&ticker={ticker}"
)

# Xtrackers: two-step direct HTTP via download.dws.com
# Step 1: GET listing page to discover document GUID
XTRACKERS_LISTING_URL = "https://download.dws.com/download/asset/product/{isin}/PRIIPS%20KID/EN/"
# Step 2: GET PDF by GUID
XTRACKERS_DOWNLOAD_URL = "https://download.dws.com/download/asset/{guid}"

# ── HTTP settings ──────────────────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/pdf,*/*",
    "Accept-Language": "en-GB,en;q=0.9",
}

# ── Rate limiting & retries ────────────────────────────────────────────────────
REQUEST_DELAY_MIN = 1.0  # seconds between requests
REQUEST_DELAY_MAX = 3.0  # seconds (randomised)
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # exponential backoff multiplier

# ── PDF validation ─────────────────────────────────────────────────────────────
PDF_MAGIC = b"%PDF-"
MIN_PDF_SIZE = 5 * 1024  # 5 KB – anything smaller is probably an error page

# ── Playwright settings (ISIN discovery only — downloads are pure HTTP) ───────
PLAYWRIGHT_TIMEOUT = 60_000  # ms – page navigation timeout
