"""Discover all ETF ISINs for Vanguard, iShares, Xtrackers, and SPDR.

Vanguard and iShares use Playwright (JS SPAs). Xtrackers and SPDR use pure HTTP.
Outputs JSON files to data/isins/<provider>.json.

Usage:
    python discover_isins.py                 # all providers
    python discover_isins.py -p vanguard     # single provider
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402
from config import (  # noqa: E402
    DATA_DIR,
    PLAYWRIGHT_TIMEOUT,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    REQUEST_HEADERS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _accept_cookies(page: object) -> None:
    """Try to dismiss common cookie/consent banners."""
    selectors = [
        # OneTrust (SPDR, many others)
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        # Vanguard
        "button:has-text('Accept all cookies')",
        # SPDR combined cookie + disclaimer modal
        "button:has-text('Accept and Save Cookies')",
        "button:has-text('Accept All Cookies')",
        # Generic patterns
        "button:has-text('Accept All')",
        "button:has-text('Accept all')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept cookies')",
        "button:has-text('I Accept')",
        "button:has-text('I agree')",
        "button:has-text('Agree')",
        "button:has-text('OK')",
        "button:has-text('Got it')",
        # iShares/BlackRock
        "a:has-text('Accept All Cookies')",
        "button:has-text('Accept All Cookies')",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click()
                log.info("Dismissed cookie banner via %s", sel)
                time.sleep(1)
                return
        except (TimeoutError, Exception) as exc:
            log.debug("Cookie selector %s failed: %s", sel, exc)
            continue


def _accept_disclaimer(page: object) -> None:
    """Try to dismiss professional/institutional investor disclaimers."""
    selectors = [
        "button:has-text('I have read and accept')",
        "button:has-text('Accept and continue')",
        "a:has-text('Continue')",
        "button:has-text('Continue')",
        "a:has-text('Individual Investor')",
        "a:has-text('individual investor')",
        "button:has-text('I am a professional investor')",
        "button:has-text('Accept')",
        "button:has-text('I confirm')",
        "a:has-text('I confirm')",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click()
                log.info("Dismissed disclaimer via %s", sel)
                time.sleep(2)
                return
        except (TimeoutError, Exception) as exc:
            log.debug("Disclaimer selector %s failed: %s", sel, exc)
            continue


# Metadata fields added by download/update — preserve when re-discovering ISINs
_METADATA_FIELDS = {"sha256", "file_size", "downloaded_at", "updated_at", "doc_date"}


def _save_isins(provider: str, funds: list[dict]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{provider}.json"

    # Load existing entries to preserve metadata fields from prior downloads
    existing: dict[str, dict] = {}
    if path.exists():
        try:
            for f in json.loads(path.read_text()):
                existing[f["isin"]] = f
        except (json.JSONDecodeError, KeyError):
            pass

    # Refuse to overwrite existing data with an empty result
    if not funds and existing:
        log.warning(
            "Discovery returned 0 ISINs for %s but %d exist on disk — keeping existing data",
            provider,
            len(existing),
        )
        return path

    cleaned = []
    for f in funds:
        entry = {k: v for k, v in f.items() if v}
        # Carry over metadata from previous download/update
        old = existing.get(f["isin"], {})
        for key in _METADATA_FIELDS:
            if key in old and old[key]:
                entry.setdefault(key, old[key])
        cleaned.append(entry)

    path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False))
    log.info("Saved %d ISINs to %s", len(cleaned), path)
    return path


def _extract_isins_from_text(text: str) -> list[str]:
    """Extract unique ISINs from raw text."""
    return list(dict.fromkeys(ISIN_RE.findall(text)))


# ── Provider-specific scrapers ─────────────────────────────────────────────────


def discover_vanguard(browser: object) -> list[dict]:
    """Scrape Vanguard UK ETF listing via GraphQL API interception.

    Vanguard loads all fund data via a GraphQL endpoint at /gpx/graphql.
    The response contains ~474 funds with ISINs embedded in document details
    and profile data. We intercept this response and parse out the ISINs.
    """
    log.info("Discovering Vanguard ETF ISINs…")
    page = browser.new_page()
    page.set_default_timeout(PLAYWRIGHT_TIMEOUT)

    graphql_funds: list[dict] = []

    def on_response(response):
        url = response.url
        if not response.ok:
            return
        # Intercept the big GraphQL response that has all fund data
        if "graphql" in url:
            try:
                data = response.json()
                if not isinstance(data, dict) or "data" not in data:
                    return
                funds_array = data["data"].get("funds")
                if not isinstance(funds_array, list) or len(funds_array) < 10:
                    return
                log.info("Captured Vanguard GraphQL with %d funds", len(funds_array))
                for fund in funds_array:
                    if not isinstance(fund, dict):
                        continue
                    # Extract fund name from portfolioLabels
                    name = ""
                    for pl in fund.get("portfolioLabels", []):
                        for label in pl.get("labels", []):
                            if label.get("name") == "fundName":
                                name = label.get("value", "")
                                break
                        if name:
                            break
                    # Extract ISIN from the fund data — stringify and regex
                    fund_str = json.dumps(fund)
                    isins = list(set(ISIN_RE.findall(fund_str)))
                    if isins:
                        # Extract ticker from profile if available
                        ticker = ""
                        currency = ""
                        profile = fund.get("profile", {})
                        if isinstance(profile, dict):
                            ticker = profile.get("ticker", "") or ""
                            currency = profile.get("baseCurrency", "") or ""
                        graphql_funds.append(
                            {
                                "isin": isins[0],
                                "name": name,
                                "ticker": ticker,
                                "share_class": "",
                                "currency": currency,
                            }
                        )
            except (ValueError, KeyError) as exc:
                log.debug("Vanguard GraphQL parse error: %s", exc)

    page.on("response", on_response)

    try:
        page.goto(
            "https://www.vanguard.co.uk/professional/product?product-type=etf",
            wait_until="domcontentloaded",
        )
    except (TimeoutError, OSError):
        log.warning("Timeout on Vanguard page load, continuing…")

    # Vanguard-specific cookie handling — the generic "OK" selector must be
    # avoided because it matches a non-cookie button on Vanguard's page.
    time.sleep(3)
    for sel in [
        "button:has-text('Accept all cookies')",
        "button:has-text('Accept All Cookies')",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                log.info("Vanguard: accepted cookies via %s", sel)
                break
        except (TimeoutError, OSError):
            continue

    # Wait for GraphQL response — it's a large payload (~16 MB)
    time.sleep(12)

    funds: list[dict] = graphql_funds

    # Fallback: extract ISINs from full page HTML
    if not funds:
        log.info("GraphQL interception failed, falling back to page scraping…")
        html = page.content()
        isins = _extract_isins_from_text(html)
        for isin in isins:
            funds.append(
                {
                    "isin": isin,
                    "name": "",
                    "ticker": "",
                    "share_class": "",
                    "currency": "",
                }
            )

    page.close()

    # Deduplicate by ISIN
    seen = set()
    deduped = []
    for f in funds:
        if f["isin"] not in seen:
            seen.add(f["isin"])
            deduped.append(f)

    log.info("Vanguard: found %d unique ISINs", len(deduped))
    return deduped


def discover_ishares(browser: object) -> list[dict]:
    """Scrape iShares UK ETF listing.

    The investor gate shows "Continue as an individual investor" — the
    "Continue" button is an <a> tag. After dismissing cookies and the gate,
    the product listing page renders with ISINs in the HTML.
    """
    log.info("Discovering iShares ETF ISINs…")
    page = browser.new_page()
    page.set_default_timeout(PLAYWRIGHT_TIMEOUT)

    captured_api: list[dict] = []

    def on_response(response):
        url = response.url
        if response.ok and any(k in url.lower() for k in ("product", "fund", "etf", "search", "screener")):
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 5:
                        captured_api.append({"url": url, "data": data})
                    elif isinstance(data, dict):
                        for key in ("data", "funds", "results", "products", "aaData", "rows"):
                            if key in data and isinstance(data[key], list) and len(data[key]) > 5:
                                captured_api.append({"url": url, "data": data[key]})
            except (ValueError, KeyError) as exc:
                log.debug("iShares API response parse error: %s", exc)

    page.on("response", on_response)

    try:
        page.goto("https://www.ishares.com/uk/individual/en/products/etf-investments")
    except (TimeoutError, OSError):
        log.warning("Timeout on iShares page load, continuing…")

    _accept_cookies(page)
    _accept_disclaimer(page)
    time.sleep(5)

    # Scroll to trigger more data loading
    for _ in range(5):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)

    # Try clicking "Show more" / "Load more" buttons
    for _ in range(10):
        try:
            more = page.locator(
                "button:has-text('Show more'), button:has-text('Load more'), a:has-text('Show more')"
            ).first
            if more.is_visible(timeout=1000):
                more.click()
                time.sleep(2)
            else:
                break
        except (TimeoutError, OSError):
            break

    funds: list[dict] = []

    # Strategy 1: XHR captured data
    if captured_api:
        log.info("Found %d API responses from iShares", len(captured_api))
        for capture in captured_api:
            for item in capture["data"]:
                isin = None
                name = None
                ticker = None
                share_class = None
                currency = None
                if isinstance(item, dict):
                    for k in ("isin", "ISIN", "isinCode", "localExchangeTicker"):
                        if k in item and ISIN_RE.match(str(item.get(k, ""))):
                            isin = item[k]
                            break
                    # iShares may nest data in columns
                    if not isin and "columns" in item:
                        for col in item["columns"]:
                            if isinstance(col, dict):
                                val = col.get("value", "")
                                if isinstance(val, str) and ISIN_RE.match(val):
                                    isin = val
                                    break
                    for k in ("name", "fundName", "localExchangeName", "productName"):
                        if k in item:
                            name = item[k]
                            break
                    for k in ("ticker", "tickerSymbol", "localExchangeTicker"):
                        if k in item:
                            ticker = item[k]
                            break
                    for k in ("shareClass", "shareClassName"):
                        if k in item:
                            share_class = item[k]
                            break
                    for k in ("currency", "baseCurrency", "inceptionCurrencyId"):
                        if k in item:
                            currency = item[k]
                            break
                elif isinstance(item, list):
                    # iShares sometimes returns data as arrays (aaData format)
                    text = " ".join(str(x) for x in item)
                    isins_found = _extract_isins_from_text(text)
                    if isins_found:
                        isin = isins_found[0]
                        name = str(item[0]) if item else ""

                if isin:
                    funds.append(
                        {
                            "isin": isin,
                            "name": name or "",
                            "ticker": ticker or "",
                            "share_class": share_class or "",
                            "currency": currency or "",
                        }
                    )

    # Strategy 2: DOM scraping — pair ISINs with fund names from table rows
    if not funds:
        log.info("Falling back to DOM table scraping for iShares…")
        # Build a map of product links: slug → fund name
        # Links like /uk/individual/en/products/253743/ishares-sp-500-b-ucits-etf-acc-fund
        product_links = page.query_selector_all('a[href*="/products/"]')
        slug_to_name: dict[str, str] = {}
        for link in product_links:
            href = link.get_attribute("href") or ""
            text = link.inner_text().strip().split("\n")[0].strip()
            # Extract slug from URL: /products/{id}/{slug}
            m = re.search(r"/products/\d+/([a-z0-9-]+)", href)
            if m and text and len(text) > 5:
                slug_to_name[m.group(1)] = text

        # Now scrape table rows for ISINs and match to names
        rows = page.query_selector_all("table tbody tr")
        for row in rows:
            text = row.inner_text()
            isins = _extract_isins_from_text(text)
            if not isins:
                continue
            isin = isins[0]
            # Find the product link in this row to get name + slug
            link = row.query_selector('a[href*="/products/"]')
            name = ""
            slug = ""
            if link:
                name = link.inner_text().strip().split("\n")[0].strip()
                href = link.get_attribute("href") or ""
                m = re.search(r"/products/\d+/([a-z0-9-]+)", href)
                if m:
                    slug = m.group(1)
            funds.append(
                {
                    "isin": isin,
                    "name": name,
                    "ticker": "",
                    "share_class": "",
                    "currency": "",
                    "slug": slug,
                }
            )

    # Strategy 3: Full page text — pair ISINs with nearby link context
    if not funds:
        log.info("Extracting ISINs from full page HTML for iShares…")
        html = page.content()
        isins = _extract_isins_from_text(html)
        for isin in isins:
            # Try to find the nearest product link before this ISIN
            isin_pos = html.find(isin)
            best_slug = ""
            best_name = ""
            if isin_pos > 0:
                chunk = html[max(0, isin_pos - 2000) : isin_pos]
                link_in_chunk = re.findall(
                    r'href="[^"]*?/products/\d+/([a-z0-9-]+)"[^>]*>([^<]+)',
                    chunk,
                )
                if link_in_chunk:
                    best_slug, best_name = link_in_chunk[-1]
                    best_name = best_name.strip()
            funds.append(
                {
                    "isin": isin,
                    "name": best_name,
                    "ticker": "",
                    "share_class": "",
                    "currency": "",
                    "slug": best_slug,
                }
            )

    page.close()

    seen = set()
    deduped = []
    for f in funds:
        if f["isin"] not in seen:
            seen.add(f["isin"])
            deduped.append(f)

    log.info("iShares: found %d unique ISINs", len(deduped))
    return deduped


def discover_xtrackers() -> list[dict]:
    """Discover Xtrackers ISINs from their sitemap — pure HTTP, no Playwright.

    The etf.dws.com sitemap.xml contains URLs with ISINs for all ~417 ETFs.
    """
    log.info("Discovering Xtrackers ETF ISINs via sitemap…")

    try:
        r = requests.get(
            "https://etf.dws.com/sitemap.xml",
            headers=REQUEST_HEADERS,
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException:
        log.error("Failed to fetch Xtrackers sitemap", exc_info=True)
        return []

    # Extract all URLs from sitemap
    urls = re.findall(r"<loc>([^<]+)</loc>", r.text)
    funds: list[dict] = []
    seen: set[str] = set()

    for url in urls:
        isins = ISIN_RE.findall(url)
        for isin in isins:
            if isin not in seen:
                seen.add(isin)
                slug = url.rsplit("/", 1)[-1] if "/" in url else ""
                # Clean slug to get a fund name
                name = slug.replace(isin, "").strip("-").replace("-", " ").strip()
                funds.append(
                    {
                        "isin": isin,
                        "name": name,
                        "ticker": "",
                        "share_class": "",
                        "currency": "",
                    }
                )

    log.info("Xtrackers: found %d unique ISINs from sitemap", len(funds))
    return funds


def discover_spdr() -> list[dict]:
    """Discover SPDR ISINs from sitemap + fund pages — pure HTTP, no Playwright.

    CRITICAL: Must capture both ISIN and ticker, as KID download URL requires both.

    1. Fetch the SSGA sitemap HTML for all ETF page URLs
    2. Extract ticker from URL slug
    3. Fetch each fund page via HTTP and extract ISIN from static HTML
    """
    log.info("Discovering SPDR ETF ISINs via sitemap…")

    # Step 1: Get ETF URLs from sitemap HTML
    try:
        r = requests.get(
            "https://www.ssga.com/ie/en_gb/intermediary/sitemap",
            headers=REQUEST_HEADERS,
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException:
        log.error("Failed to fetch SPDR sitemap", exc_info=True)
        return []

    etf_urls = re.findall(
        r'href="(https://www\.ssga\.com/ie/en_gb/intermediary/etfs/[^"]+)"',
        r.text,
    )
    etf_urls = list(dict.fromkeys(etf_urls))
    log.info("Found %d unique ETF URLs in SPDR sitemap", len(etf_urls))

    if not etf_urls:
        return []

    # Step 2: Fetch each fund page and extract ISIN + ticker
    funds: list[dict] = []

    for i, url in enumerate(etf_urls):
        slug = url.rstrip("/").rsplit("/", 1)[-1]

        # Extract ticker from URL suffix (e.g. spy4-gy)
        ticker_match = re.search(r"-([a-z0-9]{3,6}-[a-z]{2})$", slug)
        ticker = ticker_match.group(1) if ticker_match else ""

        log.info("SPDR [%d/%d] %s", i + 1, len(etf_urls), slug[:60])

        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
            if resp.status_code != 200:
                log.warning("  HTTP %d", resp.status_code)
                continue
        except requests.RequestException as e:
            log.warning("  Request error: %s", e)
            continue

        isins = _extract_isins_from_text(resp.text)
        if isins:
            # Build fund name from slug
            name = slug.replace("state-street-", "").replace("-", " ").strip()[:120]
            funds.append(
                {
                    "isin": isins[0],
                    "name": name,
                    "ticker": ticker,
                    "share_class": "",
                    "currency": "",
                }
            )
        else:
            log.warning("  No ISIN found on %s", slug[:40])

        # Rate limiting
        time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

    # Warn about missing tickers
    missing_tickers = sum(1 for f in funds if not f["ticker"])
    if missing_tickers:
        log.warning(
            "SPDR: %d/%d ISINs have no ticker — KID downloads will fail for these!",
            missing_tickers,
            len(funds),
        )

    # Deduplicate by ISIN
    seen = set()
    deduped = []
    for f in funds:
        if f["isin"] not in seen:
            seen.add(f["isin"])
            deduped.append(f)

    log.info("SPDR: found %d unique ISINs", len(deduped))
    return deduped


# ── Main ───────────────────────────────────────────────────────────────────────

# Providers that need a Playwright browser for discovery
BROWSER_PROVIDERS = {
    "vanguard": discover_vanguard,
    "ishares": discover_ishares,
}

# Providers that use pure HTTP (no browser needed)
HTTP_PROVIDERS = {
    "xtrackers": discover_xtrackers,
    "spdr": discover_spdr,
}

PROVIDERS = {**BROWSER_PROVIDERS, **HTTP_PROVIDERS}


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover ETF ISINs per provider")
    parser.add_argument(
        "--provider",
        "-p",
        choices=list(PROVIDERS.keys()),
        help="Run for a single provider (default: all)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_false",
        dest="headless",
        help="Run browser with visible UI (useful for debugging)",
    )
    args = parser.parse_args()

    providers_to_run = [args.provider] if args.provider else list(PROVIDERS.keys())

    def _run_provider(provider: str, browser: object | None = None) -> None:
        log.info("=" * 60)
        log.info("Starting ISIN discovery for %s", provider)
        log.info("=" * 60)
        try:
            if provider in BROWSER_PROVIDERS:
                funds = BROWSER_PROVIDERS[provider](browser)
            else:
                funds = HTTP_PROVIDERS[provider]()
            _save_isins(provider, funds)
        except Exception:
            log.exception("Failed to discover ISINs for %s", provider)

    # Run HTTP-only providers first (no browser needed)
    for provider in providers_to_run:
        if provider in HTTP_PROVIDERS:
            _run_provider(provider)

    # Launch browser only if any browser-based providers are requested
    browser_providers = [p for p in providers_to_run if p in BROWSER_PROVIDERS]
    if browser_providers:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=args.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                for provider in browser_providers:
                    _run_provider(provider, browser)
            finally:
                browser.close()

    # Summary
    log.info("=" * 60)
    log.info("DISCOVERY SUMMARY")
    log.info("=" * 60)
    for provider in providers_to_run:
        path = DATA_DIR / f"{provider}.json"
        if path.exists():
            data = json.loads(path.read_text())
            log.info("  %-12s: %d ISINs", provider, len(data))
        else:
            log.info("  %-12s: FAILED (no output)", provider)


if __name__ == "__main__":
    main()
